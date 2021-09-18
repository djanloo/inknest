"""
Module containing the samplers used in main calculations.

Since almost every sampler is defined by a markov chain, basic attributes are
the model and the length of the chain.

Each sampler shoud be capable of tackling with discontinuous functions.

Since is intended to be used in nested sampling, each sampler should support likelihood constrained prior sampling (LCPS).

"""
from sys import exit
import numpy as np
from numpy.random import uniform as U
from numpy.random import randint
import model
from tqdm import tqdm, trange

from timeit import default_timer as timer

BAR_FMT="{desc:<25.25}:{percentage:3.0f}%|{bar}|"
BAR_FMT_EVOL= "{desc:<25.25}:{percentage:3.0f}%|{bar:10}|"

class Sampler:
    """Produces samples from model.

    It is intended as a base class that has to be further defined.
    For generality the attribute `nwalkers` is present, but it can be one for not ensamble-based samplers.

    Attributes
    ----------
        model : model.Model
            Model defined as the set of (log_prior, log_likelihood , bounds)
        mcmc_lenght : int
            the lenght of the single markov chain
        nwalkers : int
            the number of walkers the ensamble is made of


    """
    def __init__(self, model , mcmc_length , nwalkers , verbosity=0 ):
        """Initialise the chain uniformly over the space bounds.
        """
        self.model      = model
        self.length     = mcmc_length
        self.nwalkers   = nwalkers
        self.verbosity  = verbosity
        self.elapsed_time_index = 0     #'time' index up to which self.chain has been developed


        #the squeeze method is for mantaining generality. Single-walker methods reduce to normal definition.
        self.chain      = np.zeros((self.length, self.nwalkers) , dtype=self.model.livepoint_t).squeeze()

        #uniform initialisation
        for walker in range(self.nwalkers):

            self.chain['position'][0, walker]  = U(*self.model.bounds)
            self.chain['logP'] [0, walker]      = self.model.log_prior(self.chain[0, walker]['position'])
            self.chain['logL'][0, walker]       = self.model.log_likelihood(self.chain[0, walker]['position'])


class AIESampler(Sampler):
    '''The Affine-Invariant Ensemble sampler (Goodman, Weare, 2010).

    After a uniform initialisation step, for each particle k selects a *pivot* particle an then proposes

    .. math::
        j = k + random(0 \\rightarrow n)

        z \\char`~ g(z)

        y = x_j + z (x_k - x_j)

    and then executes a MH-acceptance over y (more information at <https://msp.org/camcos/2010/5-1/camcos-v5-n1-p04-p.pdf>).

    '''

    def __init__(self, model, mcmc_length, nwalkers=10, space_scale = None, verbosity=0):

        super().__init__(model, mcmc_length, nwalkers, verbosity=verbosity)
        #if space_scale is not defined takes the 'diameter' of the space
        self.space_scale = space_scale
        if self.space_scale is None:
            self.space_scale = 0.5*np.sqrt(np.sum(self.model.bounds[0]**2)) + 0.5*np.sqrt(np.sum(self.model.bounds[1]**2))
        if self.space_scale <= 1:
            print('space scale parameter must be > 1: set 2x')
            self.space_scale *= 2

        self.duplicate_ratio = None

    def get_stretch(self, size = 1):
        '''
        Generates the stretch values given the scale_parameter ``a``.

        Output is distibuted as :math:`\\frac{1}{\\sqrt{z}}`  in :math:`[1/a,a]``.
        Uses inverse transform sampling
        '''
        return (U(0,1, size = size )*(self.space_scale**(1/2) - self.space_scale**(-1/2) ) + self.space_scale**(-1/2) )**2

    def AIEStep(self, Lthreshold=None, continuous=False):
        '''Single step of AIESampler.

            Args
            ----
                Lthreshold : float, optional
                    The threshold of likelihood below which a point is set as impossible to reach
                continuous : ``bool``, optional
                    If true use modular index assignment, overwriting past values as
                    ``self.elapsed_time_index`` > ``self.length``
        '''
        t_now  = self.elapsed_time_index
        t_next = self.elapsed_time_index + 1

        if continuous:
            t_now  = t_now  % self.length
            t_next = t_next % self.length

        #considers the whole ensamble at at time
        current_walker_position = self.chain[t_now,:]['position']

        #OPTIMIZATION: np.random.randint is really slow
        #generate a number from 1 to self.nwalkers-1
        delta_index = ((self.nwalkers-2)*np.random.rand(self.nwalkers)+1).astype(int)

        #for each walker selects randomly another walker as a pivot for the stretch move
        pivot_index     = (np.arange(self.nwalkers) + delta_index   ) % self.nwalkers
        pivot_position  = self.chain[t_now, pivot_index]['position']

        z        = self.get_stretch(size = self.nwalkers)
        proposal = pivot_position + z[:,None] * (current_walker_position - pivot_position)

        log_prior_proposal      = self.model.log_prior(proposal)
        log_likelihood_proposal = self.model.log_likelihood(proposal)
        log_prior_current       = self.chain[t_now, :]['logP']

        if not np.isfinite(log_prior_current).all():
            breakpoint()
            print(f'FATAL: past point is in impossible position')
            exit()

        #if a threshold Lmin is set, sets as 'impossible' the proposals outside
        if Lthreshold is not None:
            log_prior_proposal[log_likelihood_proposal < Lthreshold] = -np.inf

        log_accept_prob = ( self.model.space_dim - 1) * np.log(z) + log_prior_proposal - log_prior_current

        #if point is out of function domain, sets rejection
        log_accept_prob[np.isnan(log_prior_proposal)] = -np.inf

        accepted = (log_accept_prob > np.log(U(0,1,size = self.nwalkers)))

        #assigns accepted values
        self.chain['position'][t_next, accepted] = proposal[accepted]
        self.chain['logP'][t_next, accepted] = log_prior_proposal[accepted]
        self.chain['logL'][t_next, accepted] = log_likelihood_proposal[accepted]

        # copies rejected values
        self.chain[t_next, np.logical_not(accepted)] = self.chain[t_now, np.logical_not(accepted)]
        self.elapsed_time_index = t_next

    def sample_prior(self, Lthreshold = None, progress = False):
        """Fills the chain by sampling the prior.
        """
        if progress:
            desc = 'sampling prior'
            if Lthreshold is not None:
                desc += f' over logL > {Lthreshold:.2f}'
            for t in tqdm(range(self.elapsed_time_index, self.length - 1), desc = desc):
                self.AIEStep(Lthreshold = Lthreshold)
        else:
            for t in range(self.elapsed_time_index, self.length - 1):
                self.AIEStep(Lthreshold = Lthreshold)
        return self

    def reset(self, start = None):
        self.elapsed_time_index = 0
        self.chain              = np.ones((self.length, self.nwalkers) , dtype=self.model.livepoint_t).squeeze()
        if start is not None:
            assert isinstance(start, np.ndarray),   'Chain start point is not a np.ndarray'
            assert start.shape == (self.nwalkers,), 'Chain start point has wrong shape'
            self.chain[self.elapsed_time_index] = start
        else:
            print('DBG: restarting from nothing')
            exit()

    def join_chains(self, burn_in = 0.02):
        '''Joins the chains for the ensemble after removing  ``burn_in`` \% of each single_particle chain.

        Args
        ----
            burn_in : float, optional
                the burn_in percentage.

                Must be ``burn_in`` > 0 and ``burn_in`` < 1.
        '''
        return self.chain[int(burn_in*self.length):].flatten()

    def bring_over_threshold(self, logLthreshold):
        '''Brings the sampler over threshold.

        It is necessary to initialise the sampler before sampling over threshold.

        args
        ----
            Lthreshold : float
                the logarithm of the likelihood.
        '''
        logLmin = np.min(self.chain['logL'][0])
        print('ERROR: this function is no longer available due to branching to AIEevolver')
        with tqdm(total = 1, desc = 'bringing over threshold') as pbar:
            while logLmin < logLthreshold:
                sorted = np.sort(self.chain[0], order='logL')
                logLmin   = sorted['logL'][0]
                new    = self.get_new(logLmin)
                sorted = np.append(sorted, new)
                sorted = np.sort(sorted, order='logL')
                self.chain[0] = sorted[-self.nwalkers:]
                self.elapsed_time_index = 0
                pbar.n = np.exp(min(logLmin, logLthreshold) - logLthreshold  )
                pbar.refresh()

    def set_length(self, length):
        old_length  = self.length
        self.length = length
        new_chain   = np.zeros((self.length, self.nwalkers) , dtype=self.model.livepoint_t).squeeze()
        new_chain[:min(old_length, length)] = self.chain[:min(old_length, length)]
        self.chain = new_chain

class AIEevolver(AIESampler):
    '''Class to override some functionalities of the sampler
    in case only the final state is of interest.

    The main difference from AIESampler is that ``lenght`` and ``steps`` can be different

    '''
    def __init__(self, model, steps, length = None, nwalkers=10, verbosity=0):

        if length == None:
            length = 2

        super().__init__(model, length , nwalkers=nwalkers, verbosity=verbosity)
        self.steps = steps
        self.start_ensemble  = self.chain[0]

    def init(self):
        for i in tqdm(range(self.steps), desc = 'initialising sampler', colour = 'green', bar_format = BAR_FMT):
            self.AIEStep(continuous = True)
        import matplotlib.pyplot as plt
        return self

    def get_new(self,Lmin, start_ensemble = None):
        '''Returns ``nwalkers`` *different* point from prior given likelihood threshold.

        As for AIEStep, needs that every point is in a valid region (the border is included).

        If the length of the sampler is not enough to ensure that all points are different
        stretches it doubling ``self.steps`` each time. The stretch is *permanent*.

        args
        ----
            Lmin : float
                the threshold likelihood that a point must have to be accepted

        Returns:
            np.ndarray : new generated points
        '''
        if start_ensemble is not None:
            self.start_ensemble = start_ensemble
        else:
            self.start_ensemble = self.chain[self.elapsed_time_index].copy()

        import matplotlib.pyplot as plt
        #evolves the sampler at the current length
        for t in tqdm(range(self.steps), leave = False, desc = 'evolving',bar_format = BAR_FMT_EVOL):
            self.AIEStep(Lthreshold = Lmin, continuous = True)

        # this part requires a time-expensive check each loop
        # but since it is permanent it will allegedly be performed once or twice
        while True:
            #counts the duplicates
            is_duplicate    = (self.chain['logL'][self.elapsed_time_index] == self.start_ensemble['logL'][:,None]).any(axis = 0) #time comsuming op
            n_duplicate     = np.sum(is_duplicate.astype(int))

            if n_duplicate == 0:
                break
            else:
                print(f'WARNING: evolution steps extended to {2*self.steps} (runs with wrong evosteps give wrong results. \nThink about starting again.)')
                self.steps = 2*self.steps
                self.get_new(Lmin, start_ensemble = self.start_ensemble)

        return self.chain[self.elapsed_time_index]
