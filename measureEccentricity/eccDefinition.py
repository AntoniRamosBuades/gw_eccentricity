"""
Base module to measure eccentricity and mean anomaly for given waveform data.

Part of Defining eccentricity project
Md Arif Shaikh, Mar 29, 2022
"""

import numpy as np
from scipy.interpolate import InterpolatedUnivariateSpline
from .utils import get_peak_via_quadratic_fit, check_kwargs_and_set_defaults
import warnings


class eccDefinition:
    """Measure eccentricity from given waveform data dictionary."""

    def __init__(self, dataDict, spline_kwargs=None, extra_kwargs=None):
        """Init eccDefinition class.

        parameters:
        ---------
        dataDict:
            Dictionary containing waveform modes dict, time etc should follow
            the format {"t": time, "hlm": modeDict, ..}, with
            modeDict = {(l, m): hlm_mode_data}.
            For ResidualAmplitude method, also provide "t_zeroecc" and
            "hlm_zeroecc", for the quasicircular counterpart.

        spline_kwargs:
             Arguments to be passed to InterpolatedUnivariateSpline.

        extra_kwargs:
            Any extra kwargs to be passed. Allowed kwargs are
                num_orbits_to_exclude_before_merger:
                    Can be None or a non negative real number.
                    If None, the full waveform data (even post-merger) is used
                    to measure eccentricity, but this might cause issues when
                    interpolating trough extrema.
                    For a non negative real
                    num_orbits_to_exclude_before_merger, that many orbits prior
                    to merger are excluded when finding extrema.
                    Default: 1.
                extrema_finding_kwargs:
                    Dictionary of arguments to be passed to the peak finding
                    function (typically scipy.signal.find_peaks).
                debug:
                    Run additional sanity checks if True.
                    Default: True.
        """
        self.dataDict = dataDict
        self.t = self.dataDict["t"]
        self.hlm = self.dataDict["hlm"]
        self.h22 = self.hlm[(2, 2)]
        self.amp22 = np.abs(self.h22)
        # shift the time axis to make t = 0 at merger
        # t_ref would be then negative. This helps
        # when subtracting quasi circular amplitude from
        # eccentric amplitude in residual amplitude method
        self.t = self.t - get_peak_via_quadratic_fit(
            self.t, self.amp22)[0]
        self.phase22 = - np.unwrap(np.angle(self.h22))
        self.omega22 = np.gradient(self.phase22, self.t)

        if "hlm_zeroecc" in dataDict:
            self.compute_res_amp_and_omega()

        # Sanity check various kwargs and set default values
        self.spline_kwargs = check_kwargs_and_set_defaults(
            spline_kwargs, self.get_default_spline_kwargs(),
            "spline_kwargs")
        self.extra_kwargs = check_kwargs_and_set_defaults(
            extra_kwargs, self.get_default_extra_kwargs(),
            "extra_kwargs")
        if self.extra_kwargs["num_orbits_to_exclude_before_merger"] \
           is not None and \
           self.extra_kwargs["num_orbits_to_exclude_before_merger"] < 0:
            raise ValueError(
                "num_orbits_to_exclude_before_merger must be non-negative. "
                "Given value was "
                f"{self.extra_kwargs['num_orbits_to_exclude_before_merger']}")

    def get_default_spline_kwargs(self):
        """Defaults for spline settings."""
        default_spline_kwargs = {
            "w": None,
            "bbox": [None, None],
            "k": 3,
            "ext": 2,
            "check_finite": False}
        return default_spline_kwargs

    def get_default_extra_kwargs(self):
        """Defaults for additional kwargs."""
        default_extra_kwargs = {
            "num_orbits_to_exclude_before_merger": 1,
            "extrema_finding_kwargs": {},   # Gets overriden in methods like
                                            # eccDefinitionUsingAmplitude
            "debug": True
            }
        return default_extra_kwargs

    def find_extrema(self, extrema_type="maxima"):
        """Find the extrema in the data.

        parameters:
        -----------
        extrema_type:
            One of 'maxima', 'peaks', 'minima' or 'troughs'.

        returns:
        ------
        array of positions of extrema.
        """
        raise NotImplementedError("Please override me.")

    def interp_extrema(self, extrema_type="maxima"):
        """Interpolator through extrema.

        parameters:
        -----------
        extrema_type:
            One of 'maxima', 'peaks', 'minima' or 'troughs'.

        returns:
        ------
        spline through extrema, positions of extrema
        """
        extrema_idx = self.find_extrema(extrema_type)
        # experimenting wih throwing away peaks too close to merger
        # This helps in avoiding unwanted feature in the spline
        # thorugh the extrema
        if self.extra_kwargs["num_orbits_to_exclude_before_merger"] is not None:
            merger_idx = np.argmin(np.abs(self.t))
            phase22_at_merger = self.phase22[merger_idx]
            # one orbit changes the 22 mode phase by 4 pi since
            # omega22 = 2 omega_orb
            phase22_num_orbits_earlier_than_merger = (
                phase22_at_merger
                - 4 * np.pi
                * self.extra_kwargs["num_orbits_to_exclude_before_merger"])
            idx_num_orbit_earlier_than_merger = np.argmin(np.abs(
                self.phase22 - phase22_num_orbits_earlier_than_merger))
            # use only the extrema those are atleast num_orbits away from the
            # merger to avoid unphysical features like nonmonotonic
            # eccentricity near the merger
            extrema_idx = extrema_idx[extrema_idx
                                      <= idx_num_orbit_earlier_than_merger]
        if len(extrema_idx) >= 2:
            spline = InterpolatedUnivariateSpline(self.t[extrema_idx],
                                                  self.omega22[extrema_idx],
                                                  **self.spline_kwargs)
            return spline, extrema_idx
        else:
            raise Exception(
                f"Sufficient number of {extrema_type} are not found."
                " Can not create an interpolator.")

    def measure_ecc(self, tref_in):
        """Measure eccentricity and mean anomaly at reference time.

        parameters:
        ----------
        tref_in:
            Input reference time at which to measure eccentricity and mean anomaly.
            Can be a single float or an array. NOTE: eccentricity/mean_ano are
            returned on a different time array tref_out, described below.

        returns:
        --------
        tref_out:
            Output reference time where eccentricity and mean anomaly are
            measured.
            This is set as tref_out = tref_in[tref_in >= tmin && tref_in < tmax],
            where tmax = min(t_peaks[-1], t_troughs[-1]),
            and tmin = max(t_peaks[0], t_troughs[0]). This is necessary because
            eccentricity is computed using interpolants of omega_peaks and
            omega_troughs. The above cutoffs ensure that we are not extrapolating
            in omega_peaks/omega_troughs.
            In addition, if num_orbits_to_exclude_before_merger in extra_kwargs is
            not None, only the data up to that many orbits before merger is
            included when finding the t_peaks/t_troughs. This helps avoid
            unphysical features like nonmonotonic eccentricity near the merger.

        ecc_ref:
            Measured eccentricity at tref_out.

        mean_ano_ref:
            Measured mean anomaly at tref_out.
        """
        tref_in = np.atleast_1d(tref_in)
        omega_peaks_interp, self.peaks_location = self.interp_extrema("maxima")
        omega_troughs_interp, self.troughs_location = self.interp_extrema("minima")

        t_peaks = self.t[self.peaks_location]
        t_troughs = self.t[self.troughs_location]
        t_max = min(t_peaks[-1], t_troughs[-1])
        t_min = max(t_peaks[0], t_troughs[0])
        # We measure eccentricty and mean anomaly from t_min to t_max
        # note than here we do not include the tmax. This because
        # the mean anomaly is computed in such a way that it will look
        # for a peak before and after the ref time to calculate the current
        # period.
        # If ref time is tmax which could be equal to the last peak, then
        # there is no next peak and that would cause problem.
        self.tref_out = tref_in[np.logical_and(tref_in < t_max,
                                               tref_in >= t_min)]

        # Sanity checks
        # Check if tref_out is reasonable
        if len(self.tref_out) == 0:
            if tref_in[-1] > t_max:
                raise Exception(f"tref_in is later than t_max={t_max}, "
                                "which corresponds to min(last periastron "
                                "time, last apastron time).")
            if tref_in[0] < t_min:
                raise Exception(f"tref_in is earlier than t_min={t_min}, "
                                "which corresponds to max(first periastron "
                                "time, first apastron time).")
            else:
                raise Exception("tref_out is empty. This can happen if the "
                                "waveform has insufficient identifiable "
                                "periastrons/apastrons.")

        # check separation between extrema
        self.orb_phase_diff_at_peaks, \
            self.orb_phase_diff_ratio_at_peaks \
            = self.check_extrema_separation(self.peaks_location, "peaks")
        self.orb_phase_diff_at_troughs, \
            self.orb_phase_diff_ratio_at_troughs \
            = self.check_extrema_separation(self.troughs_location, "troughs")

        # Check if tref_out has a peak before and after.
        # This is required to define mean anomaly.
        # See explaination on why we do not include the last peak above.
        if self.tref_out[0] < t_peaks[0] or self.tref_out[-1] >= t_peaks[-1]:
            raise Exception("Reference time must be within two peaks.")

        # compute eccentricty from the value of omega_peaks_interp
        # and omega_troughs_interp at tref_out using the fromula in
        # ref. arXiv:2101.11798 eq. 4
        self.omega_peak_at_tref_out = omega_peaks_interp(self.tref_out)
        self.omega_trough_at_tref_out = omega_troughs_interp(self.tref_out)
        self.ecc_ref = ((np.sqrt(self.omega_peak_at_tref_out)
                         - np.sqrt(self.omega_trough_at_tref_out))
                        / (np.sqrt(self.omega_peak_at_tref_out)
                           + np.sqrt(self.omega_trough_at_tref_out)))

        @np.vectorize
        def compute_mean_ano(time):
            """
            Compute mean anomaly.
            Compute the mean anomaly using Eq.7 of arXiv:2101.11798.
            Mean anomaly grows linearly in time from 0 to 2 pi over
            the range [t_at_last_peak, t_at_next_peak], where t_at_last_peak
            is the time at the previous periastron, and t_at_next_peak is
            the time at the next periastron.
            """
            idx_at_last_peak = np.where(t_peaks <= time)[0][-1]
            t_at_last_peak = t_peaks[idx_at_last_peak]
            t_at_next_peak = t_peaks[idx_at_last_peak + 1]
            t_since_last_peak = time - t_at_last_peak
            current_period = t_at_next_peak - t_at_last_peak
            mean_ano_ref = 2 * np.pi * t_since_last_peak / current_period
            return mean_ano_ref

        # Compute mean anomaly at tref_out
        self.mean_ano_ref = compute_mean_ano(self.tref_out)

        # check if eccenricity is monotonic and convex
        if len(self.tref_out) > 1:
            self.check_monotonicity_and_convexity(
                self.tref_out, self.ecc_ref,
                debug=self.extra_kwargs["debug"])

        if len(self.tref_out) == 1:
            self.mean_ano_ref = self.mean_ano_ref[0]
            self.ecc_ref = self.ecc_ref[0]
            self.tref_out = self.tref_out[0]

        return self.tref_out, self.ecc_ref, self.mean_ano_ref

    def check_extrema_separation(self, extrema_location,
                                 extrema_type="extrema",
                                 max_orb_phase_diff_factor=1.5,
                                 min_orb_phase_diff=np.pi):
        """Check if two extrema are too close or too far."""
        orb_phase_at_extrema = self.phase22[extrema_location] / 2
        orb_phase_diff = np.diff(orb_phase_at_extrema)
        # This might suggest that the data is noisy, for example, and a
        # spurious peak got picked up.
        t_at_extrema = self.t[extrema_location][1:]
        if any(orb_phase_diff < min_orb_phase_diff):
            too_close_idx = np.where(orb_phase_diff < min_orb_phase_diff)[0]
            too_close_times = t_at_extrema[too_close_idx]
            warnings.warn(f"At least a pair of {extrema_type} are too close."
                          " Minimum orbital phase diff is "
                          f"{min(orb_phase_diff)}. Times of occurances are"
                          f" {too_close_times}")
        if any(np.abs(orb_phase_diff - np.pi)
               < np.abs(orb_phase_diff - 2 * np.pi)):
            warnings.warn("Phase shift closer to pi than 2 pi detected.")
        # This might suggest that the peak finding method missed an extrema.
        # We will check if the phase diff at an extrema is greater than
        # max_orb_phase_diff_factor times the orb_phase_diff at the
        # previous peak
        orb_phase_diff_ratio = orb_phase_diff[1:]/orb_phase_diff[:-1]
        # make it of same length as orb_phase_diff by prepending 0
        orb_phase_diff_ratio = np.append([0], orb_phase_diff_ratio)
        if any(orb_phase_diff_ratio > max_orb_phase_diff_factor):
            too_far_idx = np.where(orb_phase_diff_ratio
                                   > max_orb_phase_diff_factor)[0]
            too_far_times = t_at_extrema[too_far_idx]
            warnings.warn(f"At least a pair of {extrema_type} are too far."
                          " Maximum orbital phase diff is "
                          f"{max(orb_phase_diff)}. Times of occurances are"
                          f" {too_far_times}")
        return orb_phase_diff, orb_phase_diff_ratio

    def check_monotonicity_and_convexity(self, tref_out, ecc_ref,
                                         check_convexity=False,
                                         debug=False,
                                         t_for_ecc_test=None):
        """Check if measured eccentricity is a monotonic function of time.

        parameters:
        tref_out:
            Output reference time from eccentricty measurement
        ecc_ref:
            measured eccentricity at tref_out
        check_convexity:
            In addition to monotonicity, it will check for
            convexity as well. Default is False.
        debug:
            If True then warning is generated when length for interpolation
            is greater than 100000. Default is False.
        t_for_ecc_test:
            Time array to build a spline. If None, then uses
            a new time array with delta_t = 0.1 for same range as in tref_out
            Default is None.
        """
        spline = InterpolatedUnivariateSpline(tref_out, ecc_ref)
        if t_for_ecc_test is None:
            t_for_ecc_test = np.arange(tref_out[0], tref_out[-1], 0.1)
            len_t_for_ecc_test = len(t_for_ecc_test)
            if debug and len_t_for_ecc_test > 1e6:
                warnings.warn("time array t_for_ecc_test is too long."
                              f" Length is {len_t_for_ecc_test}")

        # Get derivative of ecc(t) using cubic splines.
        self.decc_dt = spline.derivative(n=1)(t_for_ecc_test)
        self.t_for_ecc_test = t_for_ecc_test
        self.decc_dt = self.decc_dt

        # Is ecc(t) a monotoniccally decreasing function?
        if any(self.decc_dt > 0):
            warnings.warn("Ecc(t) is non monotonic.")

        # Is ecc(t) a convex function? That is, is the second
        # derivative always positive?
        if check_convexity:
            self.d2ecc_dt = spline.derivative(n=2)(t_for_ecc_test)
            self.d2ecc_dt = self.d2ecc_dt
            if any(self.d2ecc_dt > 0):
                warnings.warn("Ecc(t) is concave.")

    def make_diagnostic_plots(self, **kwargs):
        """Make a number of diagnostic plots for the method used."""
        raise NotImplementedError("Override me please.")

    def compute_res_amp_and_omega(self):
        """Compute residual amp22 and omega22."""
        self.hlm_zeroecc = self.dataDict["hlm_zeroecc"]
        self.t_zeroecc = self.dataDict["t_zeroecc"]
        self.h22_zeroecc = self.hlm_zeroecc[(2, 2)]
        self.t_zeroecc = self.t_zeroecc - get_peak_via_quadratic_fit(
            self.t_zeroecc,
            np.abs(self.h22_zeroecc))[0]
        self.amp22_zeroecc_interp = InterpolatedUnivariateSpline(
            self.t_zeroecc, np.abs(self.h22_zeroecc))(self.t)
        self.res_amp22 = self.amp22 - self.amp22_zeroecc_interp

        self.phase22_zeroecc = - np.unwrap(np.angle(self.h22_zeroecc))
        self.omega22_zeroecc = np.gradient(self.phase22_zeroecc,
                                           self.t_zeroecc)
        self.omega22_zeroecc_interp = InterpolatedUnivariateSpline(
            self.t_zeroecc, self.omega22_zeroecc)(self.t)
        self.res_omega22 = (self.omega22
                            - self.omega22_zeroecc_interp)
