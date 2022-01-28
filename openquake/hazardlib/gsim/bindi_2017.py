# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (C) 2014-2022 GEM Foundation
#
# OpenQuake is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# OpenQuake is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with OpenQuake. If not, see <http://www.gnu.org/licenses/>.
"""
Module exports :class:`BindiEtAl2017Rjb`,
               :class:`BindiEtAl2017Rhypo`
"""
import numpy as np
from scipy.constants import g

from openquake.baselib.general import CallableDict
from openquake.hazardlib.gsim.base import GMPE, CoeffsTable
from openquake.hazardlib import const
from openquake.hazardlib.imt import PGA, SA

CONSTANTS = {"mref": 4.5, "mh": 6.5,  "rref": 1.0}


def _get_distance_scaling(dist_type, C, ctx, mag):
    """
    Implements the distance scaling function F(M, R) presented in equations
    2 and 3. In the case of Joyner-Boore distance then the fixed-depth
    term h is required
    """
    r_h = _get_rh(dist_type, C, ctx)
    return (C["c1"] + C["c2"] * (mag - CONSTANTS["mref"])) *\
        np.log(r_h / CONSTANTS["rref"]) +\
        C["c3"] * (r_h - CONSTANTS["rref"])


def _get_magnitude_scaling(C, mag):
    """
    Implements the magnitude scaling function F(M) presented in equation 4
    """
    if mag < CONSTANTS["mh"]:
        return C["e1"] + C["b1"] * (mag - CONSTANTS["mref"]) +\
            C["b2"] * ((mag - CONSTANTS["mref"]) ** 2.)
    else:
        d_m = CONSTANTS["mh"] - CONSTANTS["mref"]
        return C["e1"] + C["b3"] * (mag - CONSTANTS["mh"]) +\
            (C["b1"] * d_m) + C["b2"] * (d_m ** 2.)


_get_rh = CallableDict()


@_get_rh.add("rjb")
def _get_rh_1(kind, C, ctx):
    """
    Returns the distance incorporating the fixed depth term, h
    """
    return np.sqrt(ctx.rjb ** 2. + C["h"] ** 2.)


@_get_rh.add("rhypo")
def _get_rh_2(kind, C, ctx):
    """
    In this case only the hypocentral distance is needed - return this
    directly
    """
    return ctx.rhypo


def _get_site_term(C, vs30):
    """
    Returns the linear site amplification term given in equation 5
    """
    return C["sA"] * np.log(vs30 / 800.0)


class BindiEtAl2017Rjb(GMPE):
    """
    Implements the European GMPE of Bindi et al. (2017) for use in
    moderate-seismicity regions:

    D.Bindi, F. Cotton, S. R. Kotha, C. Bosse, D. Stromeyer and G. Gruenthal
    (2017) "Application-driven ground motion prediction equation for
    seismic hazard assessments in non-cratonic moderate-seismicity areas",
    J. Seismology, 21(5), 1201 - 1218

    Two different GMPEs are supported here
    """
    #: Supported tectonic region type is 'stable shallow crust'
    DEFINED_FOR_TECTONIC_REGION_TYPE = const.TRT.STABLE_CONTINENTAL

    #: GMPE is defined only for PGA and SA (PGV coefficients not made public)
    DEFINED_FOR_INTENSITY_MEASURE_TYPES = {PGA, SA}

    #: Supported intensity measure component is the geometric mean of two
    #: horizontal components
    DEFINED_FOR_INTENSITY_MEASURE_COMPONENT = const.IMC.AVERAGE_HORIZONTAL

    #: Supported standard deviation types are inter-event, intra-event
    #: and total
    DEFINED_FOR_STANDARD_DEVIATION_TYPES = {
        const.StdDev.TOTAL, const.StdDev.INTER_EVENT, const.StdDev.INTRA_EVENT}

    #: Required site parameter is only Vs30
    REQUIRES_SITES_PARAMETERS = {'vs30'}

    #: Required rupture parameter is magnitude
    REQUIRES_RUPTURE_PARAMETERS = {'mag'}

    #: Required distance measure is Rjb
    REQUIRES_DISTANCES = {'rjb'}

    def __init__(self, adjustment_factor=1.0, **kwargs):
        super().__init__(adjustment_factor=adjustment_factor, **kwargs)
        self.adjustment_factor = np.log(float(adjustment_factor))

    def compute(self, ctx, imts, mean, sig, tau, phi):
        """
        See :meth:`superclass method
        <.base.GroundShakingIntensityModel.compute>`
        for spec of input and result values.
        """
        [dist_type] = self.REQUIRES_DISTANCES
        for m, imt in enumerate(imts):
            C = self.COEFFS[imt]

            mean[m] = (_get_magnitude_scaling(C, ctx.mag) +
                       _get_distance_scaling(dist_type, C, ctx, ctx.mag) +
                       _get_site_term(C, ctx.vs30))

            # Mean is returned in terms of m/s^2. Need to convert to g
            mean[m] -= np.log(g)
            mean[m] += self.adjustment_factor

            tau[m] = C["tau"]
            phi[m] = C["phi"]
            sig[m] = np.sqrt(C['tau'] ** 2 + C['phi'] ** 2)

    # Joyner-Boore
    COEFFS = CoeffsTable(sa_damping=5, table="""\
    imt            e1        b1         b2         b3         c1        c2         c3         h         sA       tau       phi
    pga      0.635138  1.241105  -0.131810  -0.321920  -0.930850  0.143762  -0.010880  3.875582  -0.609150  0.495337  0.631336
    0.0100   0.635138  1.241105  -0.131810  -0.321920  -0.930850  0.143762  -0.010880  3.875582  -0.609150  0.495337  0.631336
    0.0200   0.705531  1.228780  -0.129160  -0.329230  -0.944120  0.145787  -0.010880  3.923887  -0.592970  0.502517  0.634714
    0.0220   0.744105  1.219753  -0.127760  -0.332690  -0.949970  0.146859  -0.010880  3.948754  -0.583730  0.506053  0.636035
    0.0250   0.835561  1.189969  -0.123500  -0.347660  -0.964520  0.150588  -0.010880  3.971356  -0.563480  0.514039  0.641710
    0.0290   0.960622  1.149713  -0.120600  -0.364760  -0.981940  0.156387  -0.010980  3.932630  -0.533170  0.527573  0.649664
    0.0300   0.982542  1.143429  -0.120050  -0.366740  -0.983330  0.157078  -0.011030  3.935425  -0.524880  0.530023  0.651497
    0.0320   1.025696  1.136575  -0.117720  -0.379820  -0.985510  0.157380  -0.011130  4.000214  -0.510270  0.534272  0.654810
    0.0350   1.098116  1.115775  -0.113590  -0.397190  -0.989340  0.159337  -0.011330  4.036096  -0.489150  0.541214  0.659647
    0.0360   1.123583  1.105354  -0.111820  -0.402550  -0.990680  0.160659  -0.011410  4.016974  -0.480910  0.544125  0.661352
    0.0400   1.206806  1.080443  -0.107980  -0.413370  -0.992560  0.163348  -0.011700  4.014361  -0.452990  0.556069  0.664047
    0.0420   1.237455  1.078369  -0.108240  -0.415230  -0.990520  0.163407  -0.011860  4.054173  -0.445700  0.561054  0.666271
    0.0440   1.251844  1.076735  -0.110540  -0.410250  -0.982740  0.163753  -0.012070  4.026577  -0.437860  0.567211  0.668650
    0.0450   1.251626  1.075113  -0.111940  -0.404130  -0.976750  0.163945  -0.012200  3.970955  -0.434460  0.571350  0.670589
    0.0460   1.256382  1.074434  -0.113630  -0.399360  -0.972150  0.164094  -0.012310  3.921404  -0.431610  0.575592  0.672206
    0.0480   1.273180  1.070584  -0.115800  -0.404410  -0.965450  0.164738  -0.012500  3.830608  -0.425450  0.582299  0.675478
    0.0500   1.268964  1.072599  -0.117110  -0.411960  -0.955390  0.164215  -0.012670  3.760774  -0.423150  0.584897  0.678273
    0.0550   1.294806  1.072646  -0.116210  -0.412610  -0.941150  0.162012  -0.013000  3.652581  -0.425790  0.593588  0.681858
    0.0600   1.274268  1.076568  -0.112050  -0.392960  -0.914590  0.159776  -0.013410  3.550820  -0.421100  0.598143  0.684462
    0.0650   1.284592  1.080960  -0.109190  -0.373250  -0.899380  0.157293  -0.013670  3.491090  -0.415050  0.600609  0.686179
    0.0670   1.270761  1.080915  -0.108790  -0.366810  -0.888570  0.156759  -0.013800  3.400139  -0.413930  0.601248  0.685822
    0.0700   1.259126  1.089845  -0.108850  -0.346960  -0.874880  0.154148  -0.013970  3.355068  -0.413490  0.603364  0.684155
    0.0750   1.215838  1.121748  -0.110610  -0.324150  -0.848450  0.147315  -0.014190  3.235534  -0.411620  0.602686  0.682186
    0.0800   1.151986  1.159183  -0.110220  -0.308890  -0.822660  0.139166  -0.014300  3.178012  -0.414330  0.598061  0.679445
    0.0850   1.078880  1.193976  -0.106640  -0.302760  -0.799970  0.131684  -0.014330  3.102177  -0.421470  0.593599  0.678927
    0.0900   1.016519  1.227105  -0.104830  -0.283490  -0.782200  0.124327  -0.014290  3.023759  -0.440030  0.590472  0.677846
    0.0950   0.973402  1.256189  -0.105520  -0.265790  -0.769890  0.118147  -0.014190  3.026574  -0.461320  0.582793  0.678857
    0.1000   0.925401  1.287379  -0.111830  -0.231010  -0.757490  0.112731  -0.014100  2.985996  -0.486610  0.576948  0.679655
    0.1100   0.875791  1.340574  -0.116550  -0.209500  -0.742660  0.103309  -0.013870  2.968454  -0.527410  0.558266  0.681101
    0.1200   0.828032  1.383584  -0.119730  -0.132090  -0.732610  0.093477  -0.013580  3.122213  -0.561160  0.541827  0.683444
    0.1300   0.766340  1.428531  -0.122180  -0.099120  -0.723060  0.084934  -0.013250  3.123764  -0.604790  0.522968  0.685163
    0.1330   0.752926  1.440635  -0.123390  -0.090410  -0.722610  0.082770  -0.013130  3.162190  -0.617940  0.520507  0.685210
    0.1400   0.737791  1.468425  -0.127720  -0.075320  -0.724260  0.077987  -0.012880  3.286426  -0.645450  0.512704  0.684238
    0.1500   0.736715  1.504067  -0.130450  -0.040160  -0.733400  0.071440  -0.012490  3.554848  -0.683200  0.500299  0.686074
    0.1600   0.749177  1.525331  -0.132690  -0.029340  -0.750100  0.069666  -0.012040  3.687601  -0.723930  0.488304  0.689339
    0.1700   0.760213  1.540786  -0.138410  -0.015620  -0.766220  0.069663  -0.011610  3.781996  -0.760640  0.475100  0.688702
    0.1800   0.739452  1.563804  -0.138710  -0.021800  -0.775680  0.068009  -0.011250  3.856147  -0.790880  0.462568  0.686140
    0.1900   0.730298  1.570019  -0.144490  -0.004910  -0.787040  0.069004  -0.010850  3.868169  -0.815350  0.452189  0.680811
    0.2000   0.699276  1.588260  -0.149360   0.020797  -0.791930  0.067300  -0.010520  3.870361  -0.834000  0.441413  0.676819
    0.2200   0.659139  1.637386  -0.161840   0.057295  -0.809450  0.063984  -0.009850  4.011015  -0.865780  0.430961  0.665048
    0.2400   0.585197  1.670581  -0.168330   0.047490  -0.816190  0.063724  -0.009460  4.030252  -0.907470  0.418078  0.657967
    0.2500   0.544202  1.676278  -0.169680   0.066640  -0.819600  0.065290  -0.009280  3.969146  -0.930390  0.414367  0.656646
    0.2600   0.518890  1.690318  -0.172100   0.079712  -0.827790  0.064973  -0.009020  4.004102  -0.950260  0.407553  0.654576
    0.2800   0.468023  1.718140  -0.171930   0.096277  -0.843840  0.063219  -0.008490  4.088128  -0.970900  0.402642  0.655900
    0.2900   0.449715  1.730149  -0.173960   0.103671  -0.852910  0.063330  -0.008210  4.161005  -0.978320  0.400506  0.654953
    0.3000   0.438012  1.742259  -0.179910   0.116360  -0.861500  0.063859  -0.008000  4.217235  -0.982850  0.398426  0.654131
    0.3200   0.435852  1.767679  -0.189340   0.128703  -0.883920  0.064745  -0.007540  4.439888  -0.987550  0.393950  0.650810
    0.3400   0.404536  1.797985  -0.195110   0.115054  -0.899800  0.064053  -0.007100  4.399340  -0.993250  0.384897  0.649751
    0.3500   0.382972  1.810384  -0.197220   0.099968  -0.906200  0.064678  -0.006920  4.368682  -0.999760  0.384327  0.649189
    0.3600   0.349214  1.821998  -0.198100   0.084615  -0.908870  0.065198  -0.006770  4.366836  -1.006870  0.385376  0.648155
    0.3800   0.280029  1.840613  -0.202330   0.060432  -0.910860  0.067799  -0.006580  4.269163  -1.013800  0.384998  0.647082
    0.4000   0.216017  1.862263  -0.206160   0.067862  -0.915170  0.068428  -0.006360  4.254286  -1.016590  0.383209  0.648535
    0.4200   0.172509  1.879301  -0.212120   0.083118  -0.924180  0.070022  -0.006110  4.267693  -1.014390  0.380057  0.646898
    0.4400   0.139057  1.894512  -0.220880   0.096344  -0.933450  0.072375  -0.005880  4.267138  -1.008760  0.378131  0.645543
    0.4500   0.123479  1.903496  -0.223920   0.098657  -0.938110  0.072849  -0.005780  4.314011  -1.007770  0.377127  0.645109
    0.4600   0.092663  1.914621  -0.226230   0.113557  -0.939190  0.072457  -0.005700  4.373658  -1.006970  0.374313  0.644466
    0.4800   0.064142  1.925415  -0.231520   0.119283  -0.950590  0.074303  -0.005460  4.503590  -1.004980  0.376973  0.642511
    0.5000   0.015134  1.933643  -0.229620   0.126283  -0.957250  0.074768  -0.005220  4.570597  -1.004220  0.378237  0.639470
    0.5500  -0.107970  1.951700  -0.239610   0.164680  -0.971840  0.078830  -0.004640  4.510815  -1.006060  0.383912  0.635885
    0.6000  -0.210030  1.967164  -0.235140   0.136069  -0.988640  0.082926  -0.004190  4.583048  -1.003190  0.397759  0.634794
    0.6500  -0.318340  1.994321  -0.231640   0.106534  -0.998240  0.085986  -0.003910  4.624840  -0.997570  0.410119  0.631284
    0.6670  -0.377670  1.999595  -0.227650   0.094506  -0.995190  0.087318  -0.003870  4.550387  -0.994190  0.415335  0.630272
    0.7000  -0.461320  2.010666  -0.224060   0.086120  -0.997760  0.089917  -0.003720  4.398042  -0.984550  0.421072  0.626758
    0.7500  -0.602990  2.023635  -0.222370   0.039362  -0.994020  0.095549  -0.003580  4.174297  -0.964820  0.430431  0.623797
    0.8000  -0.737520  2.041943  -0.218890   0.054982  -0.990400  0.097224  -0.003500  4.062969  -0.942860  0.437310  0.622591
    0.8500  -0.833250  2.058361  -0.213530   0.031862  -0.997750  0.099138  -0.003280  4.055099  -0.929260  0.442478  0.625612
    0.9000  -0.913750  2.082115  -0.206790  -0.001830  -1.006360  0.098959  -0.003070  4.199566  -0.928390  0.455462  0.624580
    0.9500  -1.027550  2.107107  -0.200650  -0.029910  -1.003330  0.097355  -0.002960  4.189130  -0.924830  0.471674  0.622931
    1.0000  -1.116170  2.130210  -0.201780  -0.017300  -1.006680  0.096426  -0.002820  4.231572  -0.915310  0.479707  0.620973
    1.1000  -1.281600  2.155173  -0.200600  -0.030950  -1.013040  0.100472  -0.002480  4.180282  -0.892360  0.490696  0.618982
    1.2000  -1.541750  2.181763  -0.180260  -0.031330  -0.995630  0.098812  -0.002330  4.022894  -0.881650  0.502163  0.615611
    1.3000  -1.695110  2.211878  -0.169820  -0.049360  -0.999650  0.098186  -0.002050  4.073868  -0.868980  0.520770  0.609101
    1.4000  -1.843290  2.235781  -0.158540  -0.008240  -1.008190  0.095328  -0.001720  4.219321  -0.867660  0.529452  0.604887
    1.5000  -1.901680  2.229950  -0.155900   0.012115  -1.032620  0.100703  -0.001370  4.401009  -0.852200  0.540605  0.604146
    1.6000  -2.008610  2.256904  -0.159130   0.035439  -1.040790  0.100755  -0.001170  4.443051  -0.831210  0.544404  0.600164
    1.7000  -2.131090  2.258859  -0.146030   0.043698  -1.043480  0.098506  -0.001000  4.642552  -0.809230  0.550368  0.599125
    1.8000  -2.212390  2.282670  -0.148270   0.043236  -1.051520  0.098118  -0.000850  4.880542  -0.796600  0.556535  0.598574
    1.9000  -2.293230  2.330732  -0.162870   0.083305  -1.059710  0.094681  -0.000660  5.151302  -0.795890  0.550160  0.597577
    2.0000  -2.335640  2.339893  -0.153660   0.062914  -1.081170  0.095849  -0.000450  5.404803  -0.782790  0.548455  0.594664
    2.2000  -2.583710  2.328118  -0.106080   0.085979  -1.070680  0.090160  -0.000490  5.458659  -0.769760  0.555283  0.596546
    2.4000  -2.757660  2.366893  -0.099200   0.137943  -1.065930  0.082511  -0.000430  5.577205  -0.759120  0.555954  0.590970
    2.5000  -2.911190  2.389345  -0.094020   0.174453  -1.039020  0.077098  -0.000670  5.662470  -0.738660  0.558695  0.589879
    2.6000  -2.980700  2.436770  -0.110630   0.259638  -1.035520  0.070752  -0.000670  5.977967  -0.728720  0.558466  0.587132
    2.8000  -2.985610  2.403452  -0.093490   0.313060  -1.067010  0.072788  -0.000570  6.541798  -0.685760  0.523922  0.589979
    3.0000  -3.118900  2.396847  -0.081150   0.381270  -1.063110  0.070630  -0.000670  6.815989  -0.676270  0.524274  0.591716
    3.2000  -3.296140  2.418203  -0.071370   0.439181  -1.046650  0.065154  -0.000810  7.011276  -0.663990  0.515799  0.592432
    3.4000  -3.296240  2.441129  -0.094510   0.479797  -1.057270  0.067191  -0.000870  7.209539  -0.651160  0.522075  0.588690
    3.5000  -3.327090  2.441528  -0.090670   0.504891  -1.062860  0.068069  -0.000870  7.507757  -0.643560  0.523420  0.584815
    3.6000  -3.476920  2.457411  -0.074510   0.540008  -1.039050  0.062581  -0.001010  7.768941  -0.632120  0.534581  0.581911
    3.8000  -3.568780  2.414174  -0.066080   0.556090  -1.035910  0.071428  -0.001140  7.884801  -0.631060  0.538444  0.573748
    4.0000  -3.719730  2.410756  -0.062210   0.581531  -1.020870  0.075380  -0.001280  7.944414  -0.617710  0.530623  0.568737
    """)


class BindiEtAl2017Rhypo(BindiEtAl2017Rjb):
    """
    Version of the Bindi et al. (2017) GMPE using hypocentral distance.
    """
    #: Required distance measure is Rhypo (eq. 1).
    REQUIRES_DISTANCES = set(('rhypo', ))

    # Hypocentral
    COEFFS = CoeffsTable(sa_damping=5, table="""\
    imt            e1        b1           b2          b3        c1           c2           c3        sA         tau         phi
    pga      1.494544  1.514441  -0.09357000  0.33240700  -1.15213   0.09175100  -0.00930000  -0.61492  0.50156400  0.63757400
    0.0100   1.494544  1.514441  -0.09357000  0.33240700  -1.15213   0.09175100  -0.00930000  -0.61492  0.50156400  0.63757400
    0.0200   1.570345  1.503896  -0.09074000  0.32841500  -1.16673   0.09346100  -0.00929000  -0.59877  0.50877700  0.64092400
    0.0220   1.610601  1.494865  -0.08933000  0.32517400  -1.17294   0.09459200  -0.00929000  -0.58954  0.51221500  0.64221300
    0.0250   1.715268  1.466781  -0.08502000  0.31234200  -1.19098   0.09800100  -0.00927000  -0.56930  0.52020600  0.64762700
    0.0290   1.861380  1.428625  -0.08179000  0.29794300  -1.21392   0.10342500  -0.00933000  -0.53904  0.53402200  0.65550100
    0.0300   1.886291  1.421821  -0.08125000  0.29616200  -1.21608   0.10426900  -0.00937000  -0.53074  0.53642400  0.65719700
    0.0320   1.923407  1.413206  -0.07893000  0.28318900  -1.21652   0.10507100  -0.00949000  -0.51611  0.54071300  0.66029500
    0.0350   1.998679  1.392584  -0.07470000  0.26943700  -1.22112   0.10705800  -0.00968000  -0.49500  0.54785700  0.66475400
    0.0360   2.028152  1.381789  -0.07285000  0.26414200  -1.22348   0.10849800  -0.00975000  -0.48678  0.55085900  0.66638200
    0.0400   2.109385  1.353035  -0.06875000  0.25141800  -1.22451   0.11223800  -0.01006000  -0.45885  0.56311600  0.66891400
    0.0420   2.130849  1.348203  -0.06893000  0.24849100  -1.21988   0.11301400  -0.01024000  -0.45157  0.56809300  0.67111500
    0.0440   2.139374  1.342776  -0.07114000  0.25033600  -1.21041   0.11427900  -0.01046000  -0.44371  0.57433300  0.67347500
    0.0450   2.139921  1.339719  -0.07243000  0.25529700  -1.20457   0.11480000  -0.01059000  -0.44030  0.57857200  0.67536700
    0.0460   2.145808  1.338217  -0.07400000  0.25986500  -1.20022   0.11514700  -0.01070000  -0.43746  0.58288600  0.67695800
    0.0480   2.164007  1.332446  -0.07590000  0.25331300  -1.19373   0.11626200  -0.01088000  -0.43129  0.58957800  0.68023800
    0.0500   2.158757  1.332431  -0.07709000  0.24452000  -1.18335   0.11620700  -0.01106000  -0.42897  0.59230900  0.68296200
    0.0550   2.192883  1.332603  -0.07585000  0.25047800  -1.17146   0.11400500  -0.01137000  -0.43164  0.60146300  0.68639100
    0.0600   2.164618  1.329451  -0.07168000  0.26589700  -1.14287   0.11339100  -0.01179000  -0.42686  0.60562500  0.68874400
    0.0650   2.169851  1.332136  -0.06863000  0.28788100  -1.12631   0.11130800  -0.01205000  -0.42078  0.60763400  0.69027700
    0.0670   2.159330  1.331516  -0.06817000  0.29447400  -1.11649   0.11084400  -0.01218000  -0.41964  0.60815200  0.68978000
    0.0700   2.138568  1.336694  -0.06819000  0.31214000  -1.10021   0.10913800  -0.01237000  -0.41914  0.61004800  0.68803200
    0.0750   2.088161  1.370326  -0.06962000  0.34301300  -1.07214   0.10181800  -0.01259000  -0.41729  0.60913500  0.68604000
    0.0800   2.013020  1.409712  -0.06915000  0.36648400  -1.04365   0.09311800  -0.01272000  -0.42000  0.60454300  0.68316700
    0.0850   1.926213  1.447195  -0.06540000  0.37911800  -1.01749   0.08490100  -0.01277000  -0.42717  0.59996000  0.68264100
    0.0900   1.863184  1.490262  -0.06411000  0.41339200  -1.00019   0.07517100  -0.01271000  -0.44537  0.59525600  0.68178700
    0.0950   1.816356  1.524769  -0.06400000  0.44298200  -0.98736   0.06745900  -0.01261000  -0.46721  0.58942800  0.68276300
    0.1000   1.769731  1.561097  -0.07001000  0.48625300  -0.97568   0.06073600  -0.01250000  -0.49272  0.58237600  0.68358000
    0.1100   1.713437  1.627587  -0.07485000  0.52838300  -0.95971   0.04800300  -0.01228000  -0.53342  0.56406700  0.68482000
    0.1200   1.650659  1.679477  -0.07830000  0.62138000  -0.94611   0.03595100  -0.01200000  -0.56717  0.54751100  0.68670900
    0.1300   1.587248  1.736100  -0.08075000  0.67076800  -0.93659   0.02452600  -0.01167000  -0.61086  0.52868700  0.68824800
    0.1303   1.572885  1.750059  -0.08207000  0.68211600  -0.93605   0.02189100  -0.01155000  -0.62402  0.52600300  0.68838000
    0.1400   1.552383  1.779373  -0.08622000  0.69997700  -0.93656   0.01664200  -0.01130000  -0.65256  0.51624500  0.68789600
    0.1500   1.542832  1.822970  -0.08971000  0.74863400  -0.94369   0.00828200  -0.01093000  -0.68928  0.50509700  0.68942400
    0.1600   1.560224  1.853572  -0.09209000  0.76894100  -0.96193   0.00426100  -0.01046000  -0.73004  0.49248800  0.69259000
    0.1700   1.579203  1.874846  -0.09809000  0.78589400  -0.98040   0.00282000  -0.01001000  -0.76676  0.47859900  0.69214900
    0.1800   1.560126  1.900628  -0.09861000  0.78013100  -0.99052   0.00046300  -0.00964000  -0.79702  0.46530800  0.69022300
    0.1900   1.561523  1.913600  -0.10464000  0.79985100  -1.00487  -0.00025000  -0.00923000  -0.82148  0.45437400  0.68465600
    0.2000   1.534762  1.937215  -0.10968000  0.82878000  -1.01098  -0.00329000  -0.00888000  -0.84010  0.44301400  0.68059700
    0.2200   1.486267  1.990180  -0.12257000  0.86321000  -1.02611  -0.00754000  -0.00824000  -0.87190  0.43256700  0.66935000
    0.2400   1.407764  2.026004  -0.12928000  0.84990100  -1.03164  -0.00851000  -0.00786000  -0.91362  0.41991800  0.66273500
    0.2500   1.375784  2.032175  -0.13109000  0.86268700  -1.03746  -0.00701000  -0.00766000  -0.93658  0.41548000  0.66200600
    0.2600   1.352420  2.047970  -0.13334000  0.87710100  -1.04635  -0.00787000  -0.00740000  -0.95647  0.40921100  0.66013800
    0.2800   1.310876  2.087583  -0.13339000  0.90472700  -1.06524  -0.01251000  -0.00685000  -0.97718  0.40352100  0.66127700
    0.2900   1.288881  2.100521  -0.13569000  0.90948300  -1.07335  -0.01267000  -0.00658000  -0.98462  0.40096600  0.66060000
    0.3000   1.275442  2.114611  -0.14176000  0.92162200  -1.08149  -0.01264000  -0.00637000  -0.98919  0.39883000  0.65986500
    0.3200   1.255382  2.138187  -0.15163000  0.92530000  -1.09884  -0.01132000  -0.00595000  -0.99388  0.39422400  0.65689500
    0.3400   1.234872  2.175803  -0.15724000  0.91628300  -1.11747  -0.01372000  -0.00551000  -0.99965  0.38489700  0.65633800
    0.3500   1.214958  2.188117  -0.15939000  0.89716700  -1.12411  -0.01305000  -0.00532000  -1.00617  0.38438500  0.65620900
    0.3600   1.178177  2.198759  -0.16041000  0.87692100  -1.12582  -0.01232000  -0.00519000  -1.01325  0.38563900  0.65527800
    0.3800   1.117221  2.213072  -0.16498000  0.83988600  -1.12981  -0.00874000  -0.00498000  -1.02015  0.38538000  0.65455800
    0.4000   1.053371  2.231908  -0.16904000  0.83842700  -1.13403  -0.00745000  -0.00477000  -1.02292  0.38398900  0.65644500
    0.4200   1.014572  2.248211  -0.17528000  0.84750800  -1.14429  -0.00570000  -0.00452000  -1.02071  0.38116300  0.65503100
    0.4400   0.988765  2.263190  -0.18432000  0.85492200  -1.15559  -0.00333000  -0.00427000  -1.01503  0.37938500  0.65371600
    0.4500   0.971080  2.271611  -0.18755000  0.85507600  -1.15965  -0.00273000  -0.00418000  -1.01402  0.37821100  0.65322600
    0.4600   0.934947  2.278561  -0.18987000  0.86410300  -1.15919  -0.00227000  -0.00411000  -1.01319  0.37542700  0.65263700
    0.4800   0.890134  2.282694  -0.19561000  0.85586000  -1.16594   0.00115000  -0.00392000  -1.01115  0.37804600  0.65100100
    0.5000   0.837695  2.288490  -0.19402000  0.85597200  -1.17172   0.00211100  -0.00369000  -1.01039  0.37890200  0.64813900
    0.5500   0.730056  2.304199  -0.20478000  0.87788100  -1.19033   0.00661400  -0.00308000  -1.01218  0.38382600  0.64484800
    0.6000   0.620431  2.321087  -0.20035000  0.84052000  -1.20522   0.01013500  -0.00265000  -1.00922  0.39717400  0.64339000
    0.6500   0.515740  2.346797  -0.19738000  0.79998800  -1.21571   0.01357000  -0.00237000  -1.00356  0.40864100  0.63980100
    0.6670   0.464230  2.351350  -0.19355000  0.78406800  -1.21478   0.01501100  -0.00231000  -1.00016  0.41360900  0.63869800
    0.7000   0.400679  2.363368  -0.18899000  0.77142200  -1.22305   0.01705500  -0.00211000  -0.99075  0.41944700  0.63539300
    0.7500   0.263690  2.363957  -0.18745000  0.69625900  -1.22008   0.02550900  -0.00197000  -0.97102  0.42917900  0.63348100
    0.8000   0.129816  2.375162  -0.18395000  0.69659900  -1.21642   0.02879900  -0.00189000  -0.94913  0.43599900  0.63299400
    0.8500   0.025422  2.392046  -0.17872000  0.66186200  -1.22113   0.03092100  -0.00170000  -0.93538  0.44140600  0.63645800
    0.9000  -0.069930  2.411239  -0.17222000  0.62036500  -1.22569   0.03175500  -0.00153000  -0.93452  0.45399700  0.63563800
    0.9500  -0.169440  2.440097  -0.16570000  0.59649300  -1.22731   0.02900700  -0.00136000  -0.93139  0.47009100  0.63398700
    1.0000  -0.265860  2.458374  -0.16692000  0.60123700  -1.22842   0.02921500  -0.00125000  -0.92189  0.47768700  0.63264900
    1.1000  -0.416510  2.470917  -0.16339000  0.55695800  -1.23923   0.03553300  -0.00087000  -0.89927  0.48787700  0.63147600
    1.2000  -0.676110  2.489858  -0.14316000  0.54136400  -1.22206   0.03537000  -0.00072000  -0.88874  0.49853000  0.62884300
    1.3000  -0.852810  2.521182  -0.13235000  0.51865900  -1.21955   0.03436000  -0.00051000  -0.87598  0.51607900  0.62246900
    1.4000  -1.027320  2.541416  -0.11945000  0.55094900  -1.22072   0.03196700  -0.00025000  -0.87443  0.52496000  0.61893700
    1.5000  -1.091190  2.533838  -0.11504000  0.56338100  -1.24382   0.03696100   0.00008140  -0.85909  0.53547200  0.61796200
    1.6000  -1.203170  2.569142  -0.12202000  0.59349300  -1.25013   0.03601600   0.00027400  -0.83843  0.53827100  0.61437200
    1.7000  -1.342010  2.567601  -0.10904000  0.59760200  -1.24860   0.03440000   0.00041600  -0.81596  0.54366400  0.61391700
    1.8000  -1.464790  2.583144  -0.11012000  0.58584200  -1.24529   0.03546200   0.00047500  -0.80287  0.54944500  0.61386400
    1.9000  -1.588030  2.626960  -0.12239000  0.62424800  -1.24246   0.03210200   0.00058900  -0.80291  0.54388400  0.61357700
    2.0000  -1.665130  2.630186  -0.11339000  0.59597700  -1.25353   0.03463800   0.00068900  -0.78964  0.54160400  0.61145600
    2.2000  -1.963860  2.603575  -0.06043000  0.61244200  -1.22940   0.03030700   0.00054700  -0.77741  0.54894500  0.61511200
    2.4000  -2.200470  2.650725  -0.05391000  0.67350500  -1.20835   0.02147900   0.00048400  -0.76743  0.55054600  0.61181100
    2.5000  -2.394560  2.662607  -0.05076000  0.69011300  -1.16970   0.01964100   0.00014000  -0.74665  0.55237900  0.61151800
    2.6000  -2.518890  2.699475  -0.06517000  0.76896700  -1.15124   0.01503400   0.00001320  -0.73657  0.55053000  0.60974800
    2.8000  -2.632480  2.659062  -0.04832000  0.80778700  -1.15291   0.01954700  -0.00013000  -0.69291  0.51851600  0.61430300
    3.0000  -2.841610  2.639776  -0.03570000  0.85876400  -1.12781   0.02050000  -0.00043000  -0.68331  0.51793400  0.61678100
    3.2000  -3.079350  2.656785  -0.02557000  0.91052300  -1.09559   0.01631800  -0.00069000  -0.66901  0.51229200  0.61741600
    3.4000  -3.053530  2.708866  -0.05286000  0.94438500  -1.11408   0.01575500  -0.00066000  -0.65883  0.51883900  0.61307300
    3.5000  -3.123440  2.700877  -0.04946000  0.96057000  -1.10921   0.01845800  -0.00074000  -0.65059  0.51995800  0.60896600
    3.6000  -3.315890  2.703451  -0.03308000  0.98451700  -1.07375   0.01543600  -0.00097000  -0.63882  0.53285400  0.60589900
    3.8000  -3.428990  2.646549  -0.02495000  0.97546100  -1.06479   0.02724100  -0.00115000  -0.63825  0.53727300  0.59715100
    4.0000  -3.599560  2.629226  -0.02208000  0.97803700  -1.04398   0.03440400  -0.00134000  -0.62463  0.52996100  0.59149600
    """)
