# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (C) 2019-2020, GEM Foundation
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
# along with OpenQuake.  If not, see <http://www.gnu.org/licenses/>.

import logging
import numpy

from openquake.baselib import general, datastore, parallel
from openquake.hazardlib.stats import set_rlzs_stats
from openquake.risklib import scientific
from openquake.calculators import base, views

F32 = numpy.float32
U32 = numpy.uint32


def get_loss_builder(dstore, return_periods=None, loss_dt=None):
    """
    :param dstore: datastore for an event based risk calculation
    :returns: a LossCurvesMapsBuilder instance
    """
    oq = dstore['oqparam']
    weights = dstore['weights'][()]
    eff_time = oq.investigation_time * oq.ses_per_logic_tree_path
    num_events = numpy.bincount(dstore['events']['rlz_id'])
    periods = return_periods or oq.return_periods or scientific.return_periods(
        eff_time, num_events.max())
    return scientific.LossCurvesMapsBuilder(
        oq.conditional_loss_poes, numpy.array(periods),
        loss_dt or oq.loss_dt(), weights, dict(enumerate(num_events)),
        eff_time, oq.risk_investigation_time)


def get_src_loss_table(dstore, L):
    """
    :returns:
        (source_ids, array of losses of shape (Ns, L))
    """
    alt = dstore.read_df('agg_loss_table', 'agg_id', dict(agg_id=0))
    eids = alt.event_id.to_numpy()
    evs = dstore['events'][:][eids]
    rlz_ids = evs['rlz_id']
    rup_ids = evs['rup_id']
    source_id = dstore['ruptures']['source_id'][rup_ids]
    w = dstore['weights'][:]
    acc = general.AccumDict(accum=numpy.zeros(L, F32))
    del alt['event_id']
    all_losses = numpy.array(alt)
    for source_id, rlz_id, losses in zip(source_id, rlz_ids, all_losses):
        acc[source_id] += losses * w[rlz_id]
    return zip(*sorted(acc.items()))


def post_risk(builder, krl_losses, monitor):
    """
    :returns: dictionary krl -> loss curve
    """
    res = {}
    for k, r, l, losses in krl_losses:
        res[k, r, l] = (builder.build_curves(losses, r), losses.sum())
    return res


@base.calculators.add('post_risk')
class PostRiskCalculator(base.RiskCalculator):
    """
    Compute losses and loss curves starting from an event loss table.
    """
    def pre_execute(self):
        oq = self.oqparam
        if oq.hazard_calculation_id and not self.datastore.parent:
            self.datastore.parent = datastore.read(oq.hazard_calculation_id)
            assetcol = self.datastore['assetcol']
            self.aggkey = base.save_agg_values(
                self.datastore, assetcol, oq.loss_names, oq.aggregate_by)
            aggby = self.datastore.parent['oqparam'].aggregate_by
            assert oq.aggregate_by == aggby  # temporary check
        else:
            assetcol = self.datastore['assetcol']
            self.aggkey = assetcol.tagcol.get_aggkey(oq.aggregate_by)
        self.L = len(oq.loss_names)

    def execute(self):
        oq = self.oqparam
        if oq.return_periods != [0]:
            # setting return_periods = 0 disable loss curves
            eff_time = oq.investigation_time * oq.ses_per_logic_tree_path
            if eff_time < 2:
                logging.warning(
                    'eff_time=%s is too small to compute loss curves',
                    eff_time)
                return
        if 'source_info' in self.datastore:  # missing for gmf_ebrisk
            logging.info('Building src_loss_table')
            source_ids, losses = get_src_loss_table(self.datastore, self.L)
            self.datastore['src_loss_table'] = losses
            self.datastore.set_shape_attrs('src_loss_table',
                                           source=source_ids,
                                           loss_type=oq.loss_names)
        builder = get_loss_builder(self.datastore)
        K = len(self.aggkey) if oq.aggregate_by else 0
        P = len(builder.return_periods)
        # do everything in process since it is really fast
        rlz_id = self.datastore['events']['rlz_id']
        alt_df = self.datastore.read_df('agg_loss_table', 'agg_id')
        alt_df['rlz_id'] = rlz_id[alt_df.event_id.to_numpy()]
        units = self.datastore['cost_calculator'].get_units(oq.loss_names)
        with self.monitor('agg_losses and agg_curves', measuremem=True):
            smap = parallel.Starmap(post_risk, h5=self.datastore.hdf5)
            num_curves = (K + 1) * self.R * self.L
            blocksize = int(numpy.ceil(num_curves/(oq.concurrent_tasks or 1)))
            krl_losses = []
            agg_losses = numpy.zeros((K, self.R, self.L), F32)
            agg_curves = numpy.zeros((K, self.R, self.L, P), F32)
            tot_losses = numpy.zeros((self.L, self.R), F32)
            tot_curves = numpy.zeros((self.L, self.R, P), F32)
            gb = alt_df.groupby([alt_df.index, alt_df.rlz_id])
            logging.info('Computing up to {:_d} of {:_d} curves per task'.
                         format(blocksize, num_curves))
            for (k, r), df in gb:
                for l, lname in enumerate(oq.loss_names):
                    krl_losses.append((k, r, l, df[lname]))
                    if len(krl_losses) >= blocksize:
                        smap.submit((builder, krl_losses))
                        krl_losses[:] = []
            if krl_losses:
                smap.submit((builder, krl_losses))
            for (k, r, l), (curve, loss) in smap.reduce().items():
                if k == K:  # tot
                    tot_curves[l, r] = curve
                    tot_losses[l, r] = loss
                else:  # agg
                    agg_curves[k, r, l] = curve
                    agg_losses[k, r, l] = loss
            if K:
                self.datastore['agg_curves-rlzs'] = agg_curves
                self.datastore['agg_losses-rlzs'] = agg_losses * oq.ses_ratio
                set_rlzs_stats(self.datastore, 'agg_curves',
                               agg_id=K, lti=self.L,
                               return_periods=builder.return_periods,
                               units=units)
                set_rlzs_stats(self.datastore, 'agg_losses',
                               agg_id=K, loss_types=oq.loss_names, units=units)
            self.datastore['tot_curves-rlzs'] = tot_curves
            self.datastore['tot_losses-rlzs'] = tot_losses * oq.ses_ratio
            set_rlzs_stats(self.datastore, 'tot_curves',
                           lti=self.L, return_periods=builder.return_periods,
                           units=units)
            set_rlzs_stats(self.datastore, 'tot_losses',
                           loss_types=oq.loss_names, units=units)
        return 1

    def post_execute(self, dummy):
        """
        Sanity check on tot_losses
        """
        logging.info('Mean portfolio loss\n' +
                     views.view('portfolio_loss', self.datastore))
        logging.info('Sanity check on agg_losses')
        for kind in 'rlzs', 'stats':
            agg = 'agg_losses-' + kind
            tot = 'tot_losses-' + kind
            if agg not in self.datastore:
                return
            if kind == 'rlzs':
                kinds = ['rlz-%d' % rlz for rlz in range(self.R)]
            else:
                kinds = self.oqparam.hazard_stats()
            for l in range(self.L):
                ln = self.oqparam.loss_names[l]
                for r, k in enumerate(kinds):
                    tot_losses = self.datastore[tot][l, r]
                    agg_losses = self.datastore[agg][:, r, l].sum()
                    if kind == 'rlzs' or k == 'mean':
                        ok = numpy.allclose(agg_losses, tot_losses, rtol=.001)
                        if not ok:
                            logging.warning(
                                'Inconsistent total losses for %s, %s: '
                                '%s != %s', ln, k, agg_losses, tot_losses)
