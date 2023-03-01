#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
6th Generation Seismic Hazard Model of Canada (CanadaSHM6) Interface GMMs.

The final documentation for the GMMs is being prepared. The GMMs are subject
to change up until the release of the documentation.

Preliminary documentation is available in:

Kolaj, M., Halchuk, S., Adams, J., Allen, T.I. (2020): Sixth Generation Seismic
Hazard Model of Canada: input files to produce values proposed for the 2020
National Building Code of Canada; Geological Survey of Canada, Open File 8630,
2020, 15 pages, https://doi.org/10.4095/327322

Kolaj, M., Adams, J., Halchuk, S (2020): The 6th Generation seismic hazard
model of Canada. 17th World Conference on Earthquake Engineering, Sendai,
Japan. Paper 1c-0028.

Kolaj, M., Allen, T., Mayfield, R., Adams, J., Halchuk, S (2019): Ground-motion
models for the 6th Generation Seismic Hazard Model of Canada. 12th Canadian
Conference on Earthquake Engineering, Quebec City, Canada.

"""
import numpy as np
import openquake.hazardlib.gsim.abrahamson_2015 as A15

from scipy.constants import g
from openquake.hazardlib import const
from openquake.hazardlib.imt import PGA, SA, PGV
from openquake.hazardlib.gsim.base import CoeffsTable
from openquake.hazardlib.gsim.can20.can_shm6_inslab import (
    CanadaSHM6_InSlab_ZhaoEtAl2006SSlabCascadia55, COEFFS_SITE_FACTORS,
    extrapolation_factor, CoeffsTable_CanadaSHM6)
from openquake.hazardlib.gsim.can20.can_shm6_active_crust import (
    CanadaSHM6_ActiveCrust_BooreEtAl2014, CanadaSHM6_hardrock_site_factor)
from openquake.hazardlib.gsim.abrahamson_2015 import AbrahamsonEtAl2015SInter
from openquake.hazardlib.gsim.atkinson_macias_2009 import AtkinsonMacias2009
from openquake.hazardlib.gsim.ghofrani_atkinson_2014 import (
    GhofraniAtkinson2014Cascadia)


class CanadaSHM6_Interface_AbrahamsonEtAl2015SInter(AbrahamsonEtAl2015SInter):
    """
    The Abrahramson et al., 2015 (BCHydro) Inteface GMM with CanadaSHM6
    modifications to include PGV and limit the defined period range.

    See also header in CanadaSHM6_Interface.py
    """

    MAX_SA = 10.
    MIN_SA = 0.05

    DEFINED_FOR_INTENSITY_MEASURE_TYPES = set([PGA, PGV, SA])
    experimental = True

    def compute(self, ctx: np.recarray, imts, mean, sig, tau, phi):
        """
        See :meth:`superclass method
        <.base.GroundShakingIntensityModel.compute>`
        for spec of input and result values.
                CanadaSHM6 edits: Added PGV
                          Limited GMM to the CSHM6 range of 0.05 - 10s.

        """

        C_PGA = self.COEFFS[PGA()]
        dc1_pga = self.delta_c1 or self.COEFFS_MAG_SCALE[PGA()]["dc1"]

        # compute median pga on rock (vs30=1000), needed for site response
        # term calculation
        pga1000 = np.exp(A15._compute_pga_rock(
            self.kind, self.trt, self.theta6_adj, self.faba_model,
            C_PGA, dc1_pga, ctx))
        for m, imt in enumerate(imts):

            if imt == PGV():
                imt = SA(1.92)

            # Get the coeffs
            C = self.COEFFS[imt]
            dc1 = self.delta_c1 or self.COEFFS_MAG_SCALE[imt]["dc1"]

            # Compute the mean
            mean[m] = (
                A15._compute_magnitude_term(
                    self.kind, C, dc1, ctx.mag) +
                A15._compute_distance_term(
                    self.kind, self.trt, self.theta6_adj, C, ctx) +
                A15._compute_focal_depth_term(
                    self.trt, C, ctx) +
                A15._compute_forearc_backarc_term(
                    self.trt, self.faba_model, C, ctx) +
                A15._compute_site_response_term(
                    C, ctx, pga1000))

            # Convert to velocity
            if imt == PGV():
                mean[m] = (0.897*mean[m]) + 4.835

            if self.sigma_mu_epsilon:
                sigma_mu = A15.get_stress_factor(
                    imt, self.DEFINED_FOR_TECTONIC_REGION_TYPE ==
                    const.TRT.SUBDUCTION_INTRASLAB)
                mean[m] += sigma_mu * self.sigma_mu_epsilon

            sig[m] = C["sigma"] if self.ergodic else C["sigma_ss"]
            tau[m] = C['tau']
            phi[m] = C["phi"] if self.ergodic else np.sqrt(
                C["sigma_ss"] ** 2. - C["tau"] ** 2.)


# =============================================================================
# =============================================================================


class CanadaSHM6_Interface_ZhaoEtAl2006SInterCascadia(
                                CanadaSHM6_InSlab_ZhaoEtAl2006SSlabCascadia55):
    """
    Zhao et al., 2006 Interface with Cascadia adjustment at a fixed hypo depth
    of 30 km, extrapolated to 0.05 - 10s and with modifications to the site
    term as implemented for CanadaSHM6 (see also
    CanadaSHM6_InSlab_ZhaoEtAl2006SSlabCascadia).

    See also header in CanadaSHM6_Interface.py
    """

    REQUIRES_RUPTURE_PARAMETERS = set(('mag', 'rake'))
    DEFINED_FOR_TECTONIC_REGION_TYPE = const.TRT.SUBDUCTION_INTERFACE
    DEFINED_FOR_INTENSITY_MEASURE_TYPES = set([PGA, PGV, SA])
    extrapolate_GMM = CanadaSHM6_Interface_AbrahamsonEtAl2015SInter()

    HYPO_DEPTH = 30.
    experimental = True

    def __init__(self):
        super(CanadaSHM6_Interface_ZhaoEtAl2006SInterCascadia,
              self).__init__()

        self.COEFFS_SINTER = CoeffsTable_CanadaSHM6(self.COEFFS_SINTER,
                                                    self.MAX_SA, self.MIN_SA,
                                                    self.MAX_SA_EXTRAP,
                                                    self.MIN_SA_EXTRAP)








    def get_mean_and_stddevs(self, sites, rup, dists, imt, stddev_types):
        """
        See :meth:`superclass method
        <.base.GroundShakingIntensityModel.get_mean_and_stddevs>`
        for spec of input and result values.

        CanadaSHM6 edits: modified site amplification term
                          added extrapolation beyond MAX_SA and MIN_SA to 0.05
                          - 10s
                          hard-coded hypo depth of 30km
        """
        extrapolate = False
        PGVimt = False

        if imt == PGV():
            PGVimt = True
            imt = SA(1.92)
        elif imt.period < self.MIN_SA and imt.period >= self.MIN_SA_EXTRAP:
            target_imt = imt
            imt = SA(self.MIN_SA)
            extrapolate = True
        elif imt.period > self.MAX_SA and imt.period <= self.MAX_SA_EXTRAP:
            target_imt = imt
            imt = SA(self.MAX_SA)
            extrapolate = True

        # extracting dictionary of coefficients specific to required
        # intensity measure type.
        C = self.COEFFS_ASC[imt]
        C_SINTER = self.COEFFS_SINTER[imt]
        C_SF = COEFFS_SITE_FACTORS[imt]

        # mean value as given by equation 1, p. 901, without considering the
        # faulting style and intraslab terms (that is FR, SS, SSL = 0) and the
        # inter and intra event terms, plus the magnitude-squared term
        # correction factor (equation 5 p. 909)
        mean = self._compute_magnitude_term(C, rup.mag) +\
            self._compute_distance_term(C, rup.mag, dists.rrup) +\
            self._compute_focal_depth_term(C, self.HYPO_DEPTH) +\
            self._compute_site_class_term_CanadaSHM6(C, sites.vs30, imt) + \
            self._compute_magnitude_squared_term(P=0.0, M=6.3,
                                                 Q=C_SINTER['QI'],
                                                 W=C_SINTER['WI'],
                                                 mag=rup.mag) +\
            C_SINTER['SI']

        # multiply by site factor to "convert" Japan values to Cascadia values
        # then convert from cm/s**2 to g
        mean = np.log((np.exp(mean) * C_SF["MF"]) * 1e-2 / g)

        stddevs = self._get_stddevs(C['sigma'], C_SINTER['tauI'], stddev_types,
                                    num_sites=len(sites.vs30))

        # add extrapolation factor if outside SA range (0.07 - 9.09)
        if extrapolate:
            mean += extrapolation_factor(self.extrapolate_GMM, rup, sites,
                                         dists, imt, target_imt)

        if PGVimt:
            mean = (0.897*mean) + 4.835

        return mean, stddevs

    # Coefs taken from ZhaoEtAl2006SInter
    COEFFS_SINTER = CoeffsTable(sa_damping=5, table="""\
        IMT    SI     QI      WI      tauI
        pga    0.000  0.0     0.0     0.308
        0.05   0.000  0.0     0.0     0.343
        0.10   0.000  0.0     0.0     0.403
        0.15   0.000 -0.0138  0.0286  0.367
        0.20   0.000 -0.0256  0.0352  0.328
        0.25   0.000 -0.0348  0.0403  0.289
        0.30   0.000 -0.0423  0.0445  0.280
        0.40  -0.041 -0.0541  0.0511  0.271
        0.50  -0.053 -0.0632  0.0562  0.277
        0.60  -0.103 -0.0707  0.0604  0.296
        0.70  -0.146 -0.0771  0.0639  0.313
        0.80  -0.164 -0.0825  0.0670  0.329
        0.90  -0.206 -0.0874  0.0697  0.324
        1.00  -0.239 -0.0917  0.0721  0.328
        1.25  -0.256 -0.1009  0.0772  0.339
        1.50  -0.306 -0.1083  0.0814  0.352
        2.00  -0.321 -0.1202  0.0880  0.360
        2.50  -0.337 -0.1293  0.0931  0.356
        3.00  -0.331 -0.1368  0.0972  0.338
        4.00  -0.390 -0.1486  0.1038  0.307
        5.00  -0.498 -0.1578  0.1090  0.272
        """)


class CanadaSHM6_Interface_AtkinsonMacias2009(AtkinsonMacias2009):
    """
    Atkinson and Macias, 2009 Interface GMM with an added site term following
    a modified version of BSSA14 (SS14) as implemented for CanadaSHM6.

    See also header in CanadaSHM6_Interface.py
    """
    MAX_SA = 10.
    MIN_SA = 0.05
    REQUIRES_SITES_PARAMETERS = set(('vs30',))
    DEFINED_FOR_INTENSITY_MEASURE_TYPES = set([PGA, PGV, SA])
    BSSA14 = CanadaSHM6_ActiveCrust_BooreEtAl2014()
    experimental = True

    def get_mean_and_stddevs(self, sites, rup, dists, imt, stddev_types):
        """
        See :meth:`superclass method
        <.base.GroundShakingIntensityModel.get_mean_and_stddevs>`
        for spec of input and result values.

        CanadaSHM6 edits: Added site term (from CanadaSHM6 implementation of
                                           BSSA14)
                          limited to the period range of 0.05 - 10s
        """
        PGVimt = False
        if imt == PGV():
            PGVimt = True
            imt = SA(1.92)
        elif imt.period != 0 and (imt.period < self.MIN_SA or
                                  imt.period > self.MAX_SA):
            raise ValueError(str(imt) + ' is not supported. SA must be in '
                             + 'range of ' + str(self.MIN_SA) + 's and '
                             + str(self.MAX_SA) + 's.')

        C = self.COEFFS[imt]
        mean = self._get_mean_760(rup, dists, imt)  # AM09 is for Vs30 = 760m/s
        mean += self.site_term(rup, dists, sites, imt)
        stddevs = self._get_stddevs(C, len(dists.rrup), stddev_types)

        if PGVimt:
            mean = (0.897*mean) + 4.835

        return mean, stddevs

    def _get_mean_760(self, rup, dists, imt):

        """
        See get_mean_and_stddevs in AtkinsonMacias2009
        """
        C = self.COEFFS[imt]
        imean = (self._get_magnitude_term(C, rup.mag) +
                 self._get_distance_term(C, dists.rrup, rup.mag))
        # Convert mean from cm/s and cm/s/s and from common logarithm to
        # natural logarithm
        mean = np.log((10.0 ** (imean - 2.0)) / g)

        return mean

    def site_term(self, rup, dists, sites, imt):
        """
        Site term for AM09 using the CanadaSHM6 implementation of BSSA14
        (see CanadaSHM6_ActiveCrust_BooreEtAl2014)
        """
        # get PGA for non-linear term in BSSA14
        pga760 = self._get_mean_760(rup, dists, PGA())

        C = self.BSSA14.COEFFS[imt]
        F = self.BSSA14._get_site_scaling(C, np.exp(pga760), sites,
                                          imt, [])

        return F


class CanadaSHM6_Interface_GhofraniAtkinson2014Cascadia(
                                                GhofraniAtkinson2014Cascadia):
    """
    Ghofrani and Atkinson 2014 Interface GMM with Cascadia adjustment,
    extrapolated to 0.05 - 10s and modifications to the site term as
    implemented for CanadaSHM6.

    See also header in CanadaSHM6_Interface.py
    """
    # Parameters used to extrapolate to 0.05s <= T <= 10s
    MAX_SA = 9.09
    MIN_SA = 0.07
    MAX_SA_EXTRAP = 10.0
    MIN_SA_EXTRAP = 0.05
    extrapolate_GMM = CanadaSHM6_Interface_AbrahamsonEtAl2015SInter()

    REQUIRES_SITES_PARAMETERS = set(('vs30', 'backarc'))
    DEFINED_FOR_INTENSITY_MEASURE_TYPES = set([PGA, PGV, SA])
    experimental = True

    def __init__(self):

        super(CanadaSHM6_Interface_GhofraniAtkinson2014Cascadia,
              self).__init__()

        # Need to use new CoeffsTable to be able to handle extrapolation
        self.COEFFS = CoeffsTable_CanadaSHM6(self.COEFFS, self.MAX_SA,
                                             self.MIN_SA, self.MAX_SA_EXTRAP,
                                             self.MIN_SA_EXTRAP)

    def get_mean_and_stddevs(self, sites, rup, dists, imt, stddev_types):
        """
        See :meth:`superclass method
        <.base.GroundShakingIntensityModel.get_mean_and_stddevs>`
        for spec of input and result values.

        CanadaSHM6 edits: added extrapolation beyond MAX_SA and MIN_SA to 0.05
                          - 10s
                          modified site amplification term for Vs30 >= 1100 m/s

        """
        if imt == PGV():
            extrapolate = False
        elif imt.period < self.MIN_SA and imt.period >= self.MIN_SA_EXTRAP:
            target_imt = imt
            imt = SA(self.MIN_SA)
            extrapolate = True
        elif imt.period > self.MAX_SA and imt.period <= self.MAX_SA_EXTRAP:
            target_imt = imt
            imt = SA(self.MAX_SA)
            extrapolate = True
        else:
            extrapolate = False

        C = self.COEFFS[imt]

        imean = (self._get_magnitude_term(C, rup.mag) +
                 self._get_distance_term(C, dists.rrup, sites.backarc) +
                 self._get_site_term_CanadaSHM6(C, sites.vs30, imt) +
                 self._get_scaling_term(C, dists.rrup))
        # Convert mean from cm/s and cm/s/s and from common logarithm to
        # natural logarithm
        if imt.name in "SA PGA":
            mean = np.log((10.0 ** (imean - 2.0)) / g)
        else:
            mean = np.log((10.0 ** (imean)))

        stddevs = self._get_stddevs(C, len(dists.rrup), stddev_types)

        # add extrapolation factor if outside SA range (0.07 - 9.09)
        if extrapolate:
            mean += extrapolation_factor(self.extrapolate_GMM, rup, sites,
                                         dists, imt, target_imt)

        return mean, stddevs

    def _get_site_term_CanadaSHM6(self, C, vs30, imt):
        """
        Returns the linear site scaling term following GA14 for Vs30 < 1100 m/s
        and the CanadaSHM6 hard-rock approach for Vs30 >= 1100 m/s.
        """
        # Native site factor for GA14
        GA14_vs = self._get_site_term(C, vs30)

        # Need log site factors at Vs30 = 1100 and 2000 to calculate
        # CanadaSHM6 hard rock site factors
        GA14_1100 = np.log(10**self._get_site_term(C, 1100.))
        GA14_2000 = np.log(10**self._get_site_term(C, 2000.))

        # CanadaSHM6 hard rock site factor
        F = CanadaSHM6_hardrock_site_factor(GA14_1100, GA14_2000,
                                            vs30[vs30 >= 1100], imt)

        # for Vs30 > 1100 set to CanadaSHM6 factor
        GA14_vs[vs30 >= 1100] = np.log10(np.exp(F))

        return GA14_vs
