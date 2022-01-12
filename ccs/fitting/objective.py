
#------------------------------------------------------------------------------#
#  CCS: Curvature Constrained Splines                                          #
#  Copyright (C) 2019 - 2021  CCS developers group                             #
#                                                                              #
#  See the LICENSE file for terms of usage and distribution.                   #
#------------------------------------------------------------------------------#


'''This module constructs and solves the spline objective.'''


import logging
import itertools
import pickle
import json
from collections import OrderedDict
import numpy as np
import matplotlib.pyplot as plt
from cvxopt import matrix, solvers
from scipy.linalg import block_diag

import ccs.fitting.spline_functions as sf

logger = logging.getLogger(__name__)


class Objective:
    '''Objective function for the ccs method.'''

    def __init__(self, l_twb, l_one, sto, energy_ref, gen_params, ewald=[]):
        '''Generates Objective class object.

        Args:

            l_twb (list): list of Twobody class objects
            l_one (list): list of Onebody class objects
            sto (ndarray): array containing number of atoms of each type
            energy_ref (ndarray): reference energies
            ge_params (dict) : options
            ewald (list, optional) : ewald energy values for CCS+Q

        '''

        self.l_twb = l_twb
        self.l_one = l_one
        self.sto = sto
        self.energy_ref = energy_ref
        self.ewald = np.array(ewald).reshape(-1, 1)
        self.charge_scaling = 0.0

        for kk, vv in gen_params.items():
            setattr(self, kk, vv)

        self.cols_sto = sto.shape[1]
        self.np = len(l_twb)
        self.no = len(l_one)
        self.cparams = [self.l_twb[i].cols for i in range(self.np)]
        self.ns = len(energy_ref)

        logger.debug('The reference energy : \n %s \n Number of pairs:%s',
                     self.energy_ref, self.np)

    @staticmethod
    def solver(pp, qq, gg, hh, aa, bb, maxiter=300, tol=(1e-10, 1e-10, 1e-10)):
        '''The solver for the objective.

        Args:

            pp (matrix): P matrix as per standard Quadratic Programming(QP)
                notation.
            qq (matrix): q matrix as per standard QP notation.
            gg (matrix): G matrix as per standard QP notation.
            hh (matrix): h matrix as per standard QP notation
            aa (matrix): A matrix as per standard QP notation.
            bb (matrix): b matrix as per standard QP notation
            maxiter (int, optional): maximum iteration steps (default: 300).
            tol (tuple, optional): tolerance value of the solution
                (default: (1e-10, 1e-10, 1e-10)).

        Returns:

            sol (dict): dictionary containing solution details

        '''

        solvers.options['show_progress'] = False
        solvers.options['maxiters'] = maxiter
        solvers.options['feastol'] = tol[0]
        solvers.options['abstol'] = tol[1]
        solvers.options['reltol'] = tol[2]

        if aa:
            sol = solvers.qp(pp, qq, gg, hh, aa, bb)
        else:
            sol = solvers.qp(pp, qq, gg, hh)

        return sol

    def eval_obj(self, xx):
        '''Mean squared error function.

        Args:

            xx (ndarray): the solution for the objective

        Returns:

            float: mean square error

        '''

        return np.format_float_scientific(
            np.sum((self.energy_ref - (np.ravel(self.mm.dot(xx))))**2)
            / self.ns, precision=4)

    def plot(self, model_energies):
        ''' Plots the results.

        Args:

            model_energies (ndarray): Predicted energies via splines.

        '''

        fig = plt.figure()
        nat = self.l_one[0].stomat
        for i in range(1, self.no):
            nat += self.l_one[i].stomat
        # nat = nat.flatten()
        ax1 = fig.add_subplot(1, 1, 1)
        ax1.plot(model_energies/nat, self.energy_ref/nat, 'bo')
        ax1.set_xlabel('Predicted energies [eV per atom]')
        ax1.set_ylabel('Ref. energies [eV per atom]')
        xx = [min(self.energy_ref/nat), max(self.energy_ref/nat)]
        ax1.plot(xx, xx, 'r--')
        plt.tight_layout()
        plt.savefig('CCS_fitting_summary.png')
        plt.close()

        for i in range(self.np):
            fig = plt.figure()
            xx = []
            yy = []
            ax1 = fig.add_subplot(1, 2, 1)
            for r in range(int(100*(self.l_twb[i].Rcut - self.l_twb[i].Rmin))):
                xx.append(r*0.01+self.l_twb[i].Rmin)
                yy.append(sf.spline_eval012(
                    self.l_twb[i], r*0.01+self.l_twb[i].Rmin)[0])
            ax1.set_ylim(min(yy), min([3, max(yy)]))
            ax1.set_xlabel(r'Distance [\AA]')
            ax1.set_ylabel(r'Energy [eV]')
            ax1.plot(xx, yy, '--')

            ax2 = fig.add_subplot(1, 2, 2)
            plt.hist(x=np.ravel(self.l_twb[i].dismat), bins=self.l_twb[i].interval,
                     color='g', rwidth=0.85)
            ax2.set_ylabel('Frequency of a distance')
            ax2.set_xlabel('Spline interval')
            plt.savefig('CCS_spline_summary_'+self.l_twb[i].name+'.png')
            plt.close()

    def get_coeffs(self, xx, model_energies):
        '''Plots the results.

        Args:

            xx (ndarrray): The solution array.
            model_energies (ndarray): Predicted energies via spline.

        '''

        ind = 0

        for ii in range(self.np):
            self.l_twb[ii].curvatures = np.asarray(
                xx[ind: ind + self.cparams[ii]])
            ind = ind + self.cparams[ii]
            self.l_twb[ii].s_a = np.dot(
                self.l_twb[ii].aa, self.l_twb[ii].curvatures)
            self.l_twb[ii].s_b = np.dot(
                self.l_twb[ii].bb, self.l_twb[ii].curvatures)
            self.l_twb[ii].s_c = np.dot(
                self.l_twb[ii].cc, self.l_twb[ii].curvatures)
            self.l_twb[ii].s_d = np.dot(
                self.l_twb[ii].dd, self.l_twb[ii].curvatures)

            splderivs = sf.spline_eval012(self.l_twb[ii], self.l_twb[ii].Rmin)

            expcoeffs = sf.get_expcoeffs(*splderivs, self.l_twb[ii].Rmin)
            expbuf = 0.5
            self.l_twb[ii].expcoeffs = expcoeffs

            rexp = np.linspace(
                self.l_twb[ii].Rmin - expbuf, self.l_twb[ii].Rmin,
                int(expbuf / self.l_twb[ii].dx) + 1)

            expvals = sf.get_exp_values(expcoeffs, rexp)
            s_a = np.insert(self.l_twb[ii].s_a, 0, splderivs[0])

            splcoeffs = sf.get_spline_coeffs(self.l_twb[ii].interval, s_a,
                                             splderivs[1], 0)
            self.l_twb[ii].splcoeffs = np.asarray(splcoeffs)
            sf.write_splinerep(
                self.l_twb[ii].name + '.spl',
                np.array(expcoeffs).tolist(),
                splcoeffs,
                self.l_twb[ii].interval,
                self.l_twb[ii].Rcut,
                self.l_twb[ii].dx)

    def list_iterator(self):
        '''Iterates over the self.np attribute.'''

        tmp = []
        for elem in range(self.np):
            if self.l_twb[elem].Swtype == 'rep':
                tmp.append([self.l_twb[elem].cols])
            if self.l_twb[elem].Swtype == 'att':
                tmp.append([0])
            if self.l_twb[elem].Swtype == 'sw':
                tmp.append(self.l_twb[elem].indices)

        n_list = list(itertools.product(*tmp))

        return n_list

    def solution(self):
        '''Function to solve the objective with constraints.'''

        self.mm = self.get_m()
        logger.debug('\n Shape of M matrix is : %s', self.mm.shape)

        pp = matrix(np.transpose(self.mm).dot(self.mm))
        eigvals = np.linalg.eigvals(pp)

        logger.debug('Eigenvalues:%s', eigvals)
        logger.info('positive definite:%s', np.all((eigvals > 0)))

        qq = -1 * matrix(np.transpose(self.mm).dot(self.energy_ref))
        nswitch_list = self.list_iterator()
        obj = []
        sol_list = []

        for n_switch_id in nswitch_list:
            [gg, aa] = self.get_g(n_switch_id)
            hh = np.zeros(gg.shape[0])
            bb = np.zeros(aa.shape[0])
            sol = self.solver(pp, qq, matrix(gg), matrix(hh), matrix(aa),
                              matrix(bb))
            obj.append(float(self.eval_obj(sol['x'])))
            sol_list.append(sol)

        obj = np.asarray(obj)
        mse = np.min(obj)
        opt_sol_index = int(np.ravel(np.argwhere(obj == mse)))

        logger.info('\n The best switch is : %s and mse : %s',
                    nswitch_list[opt_sol_index], mse)

        [g_opt, aa] = self.get_g(nswitch_list[opt_sol_index])
        bb = np.zeros(aa.shape[0])
        opt_sol = self.solver(pp, qq, matrix(g_opt), matrix(hh), matrix(aa),
                              matrix(bb))

        xx = np.array(opt_sol['x'])

        # ASSIGN VALUES
        counter = -1
        if(self.interface == "CCS+Q"):
            counter = 0
            self.charge_scaling = (xx[-1]**0.5)
        for k in range(self.no):
            i = self.no-k-1
            if(self.l_one[i].epsilon_supported):
                counter += 1
                self.l_one[i].epsilon = float(xx[-1-counter])

        model_energies = np.ravel(self.mm.dot(xx))

        self.get_coeffs(list(xx), model_energies)
        self.plot(model_energies)
        sf.write_error(model_energies, self.energy_ref, mse)
        sf.write_CCS_params(self)

        # PERFORM SENSITIVITY TEST
        #  J Obective
        #  dJ/dc_i    =  0    ?
        #  d2J/dc_i2  =  V_i* (V_i*) T  ?
        #  Harmonic approximation...
        for i in range(np.shape(self.mm)[1]):
            logger.info(str(np.dot(self.mm[:, i], self.mm[:, i])) +
                        " " + str(np.dot(self.mm[:, i], self.mm[:, i]*xx[i])))
        # /PERFORM SENSI...

        return model_energies, mse, xx

    def predict(self, xx):
        '''Predict results.

        Args:

            xx (ndarrray): Solution array from training.

        '''
        self.mm = self.get_m()
        try:
            model_energies = np.ravel(self.mm.dot(xx))
            error = (model_energies-self.energy_ref)
            mse = ((error) ** 2).mean()
        except:
            model_energy = []
            error = []
            mse = 0

        sf.write_error(model_energies, self.energy_ref,
                       mse, fname='error_test.out')
        return model_energies, error

    def get_m(self):
        '''Returns the M matrix.

        Returns:

            ndarray: The M matrix.

        '''

        tmp = []
        for ii in range(self.np):
            tmp.append(self.l_twb[ii].vv)
            logger.debug('\n The %d pair v matrix is :\n %s', ii,
                         self.l_twb[ii].vv)
        vv = np.hstack([*tmp])
        logger.debug('\n The V-matrix shape after stacking :\t %s', vv.shape)
        mm = np.hstack((vv, self.sto))

        if self.interface == 'CCS+Q':
            mm = np.hstack((mm, self.ewald))

        return mm

    def get_g(self, n_switch):
        '''Returns constraints matrix.

        Args:

            n_switch (int): switching point to change signs of curvatures.

        Returns:

            ndarray: returns G and A matrix

        '''

        aa = np.zeros(0)
        if self.ctype is None:
            tmp_g = []
            for ii in range(self.np):
                tmp_g.append(
                    block_diag(-1 * np.identity(n_switch[ii]),
                               np.identity(self.l_twb[ii].cols - n_switch[ii])))
            gg = block_diag(*tmp_g)
        # Place to add custom constraints on G matrix

        if self.ctype == 'mono':
            tmp = []
            for elem in range(self.np):
                g_mono = -1 * np.identity(self.l_twb[elem].cols)
                ii, jj = np.indices(g_mono.shape)
                g_mono[ii == jj - 1] = 1
                g_mono[ii > n_switch[elem]] = -g_mono[ii > n_switch[elem]]
                tmp.append(g_mono)
            gg = block_diag(*tmp)
        if self.smooth == 'True':
            n_gaps = 0
            wid = self.cols_sto
            for elem in range(self.np):
                n_gaps = (
                    n_gaps + self.l_twb[elem].cols - 2 - sum(
                        self.l_twb[elem].mask[1: self.l_twb[elem].cols - 1]))
                wid = wid + self.l_twb[elem].cols
            if self.interface == 'CCS+Q':
                wid = wid + 1
            if n_gaps > 0:
                aa = np.zeros([np.int(n_gaps), wid])
                cnt1 = -1
                cnt2 = 0
                for elem in range(self.np):
                    for ii in range(1, self.l_twb[elem].cols - 1):
                        if self.l_twb[elem].mask[ii] == 0 \
                           and ii != n_switch[elem]:
                            cnt1 = cnt1 + 1
                            aa[cnt1][cnt2 + ii - 1] = 1
                            aa[cnt1][cnt2 + ii] = -2
                            aa[cnt1][cnt2 + ii + 1] = 1
                    cnt2 = cnt2 + self.l_twb[elem].cols
                aa = aa[~np.all(aa == 0, axis=1)]
            else:
                aa = np.zeros(0)

        gg = block_diag(gg, np.zeros_like(np.eye(self.cols_sto)))
        if self.interface == 'CCS+Q':
            gg = block_diag(gg, 0)

        return gg, aa