# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (C) 2014-2021 GEM Foundation
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

import os
import logging
import numpy
from openquake.baselib import general, parallel
from openquake.baselib.python3compat import encode
from openquake.baselib.general import (
    AccumDict, block_splitter, groupby, get_nbytes_msg)
from openquake.hazardlib.contexts import basename
from openquake.hazardlib.source.point import grid_point_sources, msr_name
from openquake.hazardlib.source.base import get_code2cls
from openquake.hazardlib.sourceconverter import SourceGroup
from openquake.hazardlib.calc.filters import split_source, SourceFilter
from openquake.calculators import base

U16 = numpy.uint16
U32 = numpy.uint32
F32 = numpy.float32
F64 = numpy.float64
TWO32 = 2 ** 32


def zero_times(sources):
    # src.id -> nrups, nsites, time, weight
    calc_times = AccumDict(accum=numpy.zeros(4, F32))
    for src in sources:
        row = calc_times[basename(src)]
        row[0] += src.num_ruptures
        row[1] += src.nsites
        row[3] += src.weight
    return calc_times


def run_preclassical(calc):
    """
    :param csm: a CompositeSourceModel
    :param oqparam: the parameters in job.ini file
    :param h5: a DataStore instance
    """
    csm = calc.csm
    oqparam = calc.oqparam
    h5 = calc.datastore.hdf5
    srcfilter = SourceFilter(
        csm.sitecol.reduce(10000) if csm.sitecol else None,
        oqparam.maximum_distance)
    # do nothing for atomic sources except counting the ruptures
    atomic_sources = csm.get_sources(atomic=True)
    normal_sources = csm.get_sources(atomic=False)
    srcfilter.set_weight(atomic_sources)

    # run preclassical for non-atomic sources
    sources_by_grp = groupby(
        normal_sources, lambda src: (src.grp_id, msr_name(src)))
    if csm.sitecol:
        logging.info('Sending %s', srcfilter.sitecol)
    if oqparam.ps_grid_spacing:
        # produce a preclassical task for each group
        allargs = ((srcs, srcfilter, oqparam)
                   for srcs in sources_by_grp.values())
    else:
        # produce many preclassical task
        maxw = sum(len(srcs) for srcs in sources_by_grp.values()) / (
            oqparam.concurrent_tasks or 1)
        allargs = ((blk, srcfilter, oqparam)
                   for srcs in sources_by_grp.values()
                   for blk in block_splitter(srcs, maxw))
    if atomic_sources:  # case_35
        n = len(atomic_sources)
        atomic = AccumDict({'before': n, 'after': n})
        for grp_id, srcs in groupby(
                atomic_sources, lambda src: src.grp_id).items():
            atomic[grp_id] = srcs
    else:
        atomic = AccumDict()
    normal = parallel.Starmap(
        preclassical, allargs,  h5=h5,
        distribute=None if len(sources_by_grp) > 1 else 'no'
    ).reduce()
    res = atomic + normal
    if res['before'] != res['after']:
        logging.info('Reduced the number of point sources from {:_d} -> {:_d}'.
                     format(res['before'], res['after']))
    acc = AccumDict(accum=0)
    code2cls = get_code2cls()
    for grp_id, srcs in res.items():
        # srcs can be empty if the minimum_magnitude filter is on
        if srcs and not isinstance(grp_id, str) and grp_id not in atomic:
            # check if OQ_SAMPLE_SOURCES is set
            ss = os.environ.get('OQ_SAMPLE_SOURCES')
            if ss:
                logging.info('Reduced num_sources for group #%d', grp_id)
                srcs = general.random_filter(srcs, float(ss)) or [srcs[0]]
            newsg = SourceGroup(srcs[0].tectonic_region_type)
            newsg.sources = srcs
            csm.src_groups[grp_id] = newsg
            for src in srcs:
                acc[src.code] += int(src.num_ruptures)
    for val, key in sorted((val, key) for key, val in acc.items()):
        cls = code2cls[key].__name__
        logging.info('{} ruptures: {:_d}'.format(cls, val))

    calc_times = zero_times(csm.get_sources())
    calc.store_source_info(calc_times)

    # sanity check
    for sg in csm.src_groups:
        for src in sg:
            assert src.num_ruptures
            assert src.weight

    # store ps_grid data, if any
    for key, sources in res.items():
        if isinstance(key, str) and key.startswith('ps_grid/'):
            arrays = []
            for ps in sources:
                if hasattr(ps, 'location'):
                    lonlats = [ps.location.x, ps.location.y]
                    for src in getattr(ps, 'pointsources', []):
                        lonlats.extend([src.location.x, src.location.y])
                    arrays.append(F32(lonlats))
            h5[key] = arrays

    h5['full_lt'] = csm.full_lt
    return res


def preclassical(srcs, srcfilter, oqparam, monitor):
    """
    Weight the sources. Also split them if split_sources is true. If
    ps_grid_spacing is set, grid the point sources before weighting them.

    NB: srcfilter can be on a reduced site collection for performance reasons
    """
    split_sources = []
    spacing = oqparam.ps_grid_spacing
    grp_id = srcs[0].grp_id
    if srcfilter.sitecol is None:
        # in csm2rup just split the sources and count the ruptures
        for src in srcs:
            ss = split_source(src)
            if len(ss) > 1:
                for ss_ in ss:
                    ss_.nsites = 1
            split_sources.extend(ss)
            src.num_ruptures = src.count_ruptures()
        dic = {grp_id: split_sources}
        dic['before'] = len(srcs)
        dic['after'] = len(dic[grp_id])
        return dic

    with monitor('splitting sources'):
        # this can be slow
        for src in srcs:
            # NB: this is approximate, since the sitecol is sampled!
            nsites = len(srcfilter.close_sids(src))  # can be 0
            # NB: it is crucial to split only the close sources, for
            # performance reasons (think of Ecuador in SAM)
            splits = split_source(src) if (
                oqparam.split_sources and nsites) else [src]
            split_sources.extend(splits)
    dic = grid_point_sources(split_sources, spacing, monitor)
    with monitor('weighting sources'):
        srcfilter.set_weight(dic[grp_id])
    dic['before'] = len(split_sources)
    dic['after'] = len(dic[grp_id])
    if spacing:
        dic['ps_grid/%02d' % monitor.task_no] = dic[grp_id]
    return dic


@base.calculators.add('preclassical')
class PreClassicalCalculator(base.HazardCalculator):
    """
    PreClassical PSHA calculator
    """
    core_task = preclassical
    accept_precalc = []

    def get_source_ids(self):
        """
        :returns: the unique source IDs contained in the composite model
        """
        oq = self.oqparam
        self.M = len(oq.imtls)
        self.L1 = oq.imtls.size // self.M
        sources = encode([src_id for src_id in self.csm.source_info])
        size, msg = get_nbytes_msg(
            dict(N=self.N, R=self.R, M=self.M, L1=self.L1, Ns=self.Ns))
        ps = 'pointSource' in self.full_lt.source_model_lt.source_types
        if size > TWO32 and not ps:
            raise RuntimeError('The matrix disagg_by_src is too large: %s'
                               % msg)
        elif size > TWO32:
            msg = ('The source model contains point sources: you cannot set '
                   'disagg_by_src=true unless you convert them to multipoint '
                   'sources with the command oq upgrade_nrml --multipoint %s'
                   ) % oq.base_path
            raise RuntimeError(msg)
        return sources

    def init(self):
        super().init()
        if self.oqparam.hazard_calculation_id:
            full_lt = self.datastore.parent['full_lt']
            trt_smrs = self.datastore.parent['trt_smrs'][:]
        else:
            full_lt = self.csm.full_lt
            trt_smrs = self.csm.get_trt_smrs()
        self.grp_ids = numpy.arange(len(trt_smrs))
        rlzs_by_gsim_list = full_lt.get_rlzs_by_gsim_list(trt_smrs)
        rlzs_by_g = []
        for rlzs_by_gsim in rlzs_by_gsim_list:
            for rlzs in rlzs_by_gsim.values():
                rlzs_by_g.append(rlzs)
        self.datastore.hdf5.save_vlen(
            'rlzs_by_g', [U32(rlzs) for rlzs in rlzs_by_g])

    def execute(self):
        """
        Run `preclassical(srcs, srcfilter, params, monitor)` by
        parallelizing on the sources according to their weight and
        tectonic region type.
        """
        self.set_psd()  # set the pointsource_distance, needed for ps_grid_spc
        run_preclassical(self)
        return self.csm

    def set_psd(self):
        """
        Set the pointsource_distance
        """
        oq = self.oqparam
        mags = self.datastore['source_mags']  # by TRT
        if len(mags) == 0:  # everything was discarded
            raise RuntimeError('All sources were discarded!?')
        mags_by_trt = {}
        for trt in mags:
            mags_by_trt[trt] = mags[trt][()]
        psd = oq.pointsource_distance
        if psd is not None:
            psd.interp(mags_by_trt)
            for trt, dic in psd.ddic.items():
                # the sum is zero for {'default': [(1, 0), (10, 0)]}
                if sum(dic.values()):
                    it = list(dic.items())
                    dists = {i[1] for i in it}
                    if len(set(dists)) > 1:
                        md = '%s->%d ... %s->%d' % (it[0] + it[-1])
                        logging.info('ps_dist %s: %s', trt, md)
        return psd

    def post_execute(self, csm):
        """
        Store the CompositeSourceModel in binary format
        """
        if self.oqparam.calculation_mode == 'preclassical' or os.environ.get(
                'OQ_SAMPLE_SOURCES'):
            self.datastore['_csm'] = csm
