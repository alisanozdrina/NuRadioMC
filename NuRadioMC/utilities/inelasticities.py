import numpy as np
from NuRadioReco.utilities import units
from scipy import constants
from scipy import interpolate as intp
import pickle
import lzma
import logging
logging.basicConfig()
logger = logging.getLogger('inelasticities')


e_mass = constants.physical_constants['electron mass energy equivalent in MeV'][0] * units.MeV
mu_mass = constants.physical_constants['muon mass energy equivalent in MeV'][0] * units.MeV
# Mass energy equivalent of the tau lepton
tau_mass = constants.physical_constants['tau mass energy equivalent in MeV'][0] * units.MeV
pi_mass = 139.57061 * units.MeV
rho770_mass = 775.49 * units.MeV
rho1450_mass = 1465 * units.MeV
a1_mass = 1230 * units.MeV
cspeed = constants.c * units.m / units.s
G_F = constants.physical_constants['Fermi coupling constant'][0] * units.GeV ** (-2)

nu_energies_ref, yy_ref, flavors_ref, ncccs_ref, dsigma_dy_ref = pickle.load(lzma.open("BGR18_dsigma_dy.xz"))
ncccs_ref = np.array(ncccs_ref)


def get_neutrino_inelasticity(n_events, model="CTW", rnd=None,
                              nu_energies=1 * units.EeV, flavors=12, ncccs="CC"):
    """
    Standard inelasticity for deep inelastic scattering used so far.
    Ported from ShelfMC

    Parameters
    ----------
    n_events: int
        Number of events to be returned
    model: string
        the inelasticity model to use
    rnd: random generator object
        if None is provided, a new default random generator object is initialized
    Returns
    -------
    inelasticies: array
        Array with the inelasticities
    """
    if(rnd is None):
        rnd = np.random.default_rng()
    if model == "CTW":
        R1 = 0.36787944
        R2 = 0.63212056
        return (-np.log(R1 + rnd.uniform(0., 1., n_events) * R2)) ** 2.5

    if model == "BGR18":
        yy = np.zeros(n_events)
        uEE = np.unique(nu_energies)
        uFlavor = np.unique(flavors)
        uNCCC = np.unique(ncccs)
        for E in uEE:
            if(E > 10 * units.EeV):
                logger.warning(f"You are requesting inelasticities for energies outside of the validity of the BGR18 model. You requested {E/units.eV:.2g}eV. Largest available energy is 10EeV, returning result for 10EeV.")
            for flavor in uFlavor:
                for nccc in uNCCC:
                    mask = (nu_energies == E) & (flavor == flavors) & (nccc == ncccs)
                    nccc = nccc.upper()
                    iF = np.argwhere(flavors_ref == flavor)[0][0]
                    inccc = np.argwhere(ncccs_ref == nccc)[0][0]
                    iE = np.argmin(np.abs(E - nu_energies_ref))
                    print(f"{iF} {flavor}, {iE} {E}, {inccc} {nccc}")
                    get_y = intp.interp1d(np.log10(yy_ref), np.log10(dsigma_dy_ref[iF, inccc, iE]), fill_value="extrapolate", kind="cubic")
                    yyy = np.linspace(0, 1, 1000)
                    yyy = 0.5 * (yyy[:-1] + yyy[1:])
                    dsigma_dyy = 10 ** get_y(np.log10(yyy))

                    yy[mask] = rnd.choice(yyy, size=np.sum(mask), p=dsigma_dyy / np.sum(dsigma_dyy))
        return yy
    else:
        raise AttributeError(f"inelasticity model {model} is not implemented.")


def get_ccnc(n_events, rnd=None):
    """
    Get the nature of the interaction current: cc or nc
    Ported from Shelf MC
    https://github.com/persic/ShelfMC/blob/daf56916d85de019e848f415c2e9f4643a744674/functions.cc#L1055-L1064
    based on CTW cross sections https://link.aps.org/doi/10.1103/PhysRevD.83.113009

    Parameters
    ----------
    n_events: int
        Number of events to be returned
    rnd: random generator object
        if None is provided, a new default random generator object is initialized

    Returns
    -------
    ccnc: array
        Array with 'cc' or 'nc'
    """
    if(rnd is None):
        rnd = np.random.default_rng()
    random_sequence = rnd.uniform(0., 1., n_events)
    ccnc = []
    for i, r in enumerate(random_sequence):
        #    if (r <= 0.6865254):#from AraSim
        if(r <= 0.7064):
            ccnc.append('cc')
        else:
            ccnc.append('nc')

    return np.array(ccnc)


def random_tau_branch(rnd=None):
    """
    Calculates a random tau branch decay
    See http://dx.doi.org/10.1016/j.cpc.2013.04.001
    
    rnd: random generator object
        if None is provided, a new default random generator object is initialized

    Returns
    -------
    branch: string
        The corresponding decay branch
    """
    if(rnd is None):
        rnd = np.random.default_rng()

    branching_ratios = np.array([0.18, 0.18])
    branching = rnd.uniform(0, 1)
    if (branching < np.sum(branching_ratios[0:1])):
        # tau -> nu_tau + mu + nu_tau
        branch = 'tau_mu'
    elif (branching < np.sum(branching_ratios[0:2])):
        # tau -> nu_tau + e + nu_e
        branch = 'tau_e'
    else:
        # tau -> nu_tau + hadrons
        branch = 'tau_had'

    return branch


def inelasticity_tau_decay(tau_energy, branch, rnd=None):
    """
    Returns the hadronic or electromagnetic inelasticity for the tau decay
    See http://dx.doi.org/10.1016/j.cpc.2013.04.001
    and https://arxiv.org/pdf/1607.00193.pdf

    Parameters
    ----------
    tau_energy: float
        Tau energy at the moment of decay
    branch: string
        Type of tau decay: 'tau_mu', 'tau_e', 'tau_had'
    rnd: random generator object
        if None is provided, a new default random generator object is initialized

    Returns
    -------
    inelasticity: float
        The fraction of energy carried by the leptonic or hadronic products
    """
    if(rnd is None):
        rnd = np.random.default_rng()
    if (branch == 'tau_had'):

        branching = np.array([0.12, 0.26, 0.13, 0.13])
        rs = np.array([pi_mass, rho770_mass, a1_mass, rho1450_mass]) / tau_mass

        def g_pi(y, r):
            if (y < 0 or y > 1 - r ** 2):
                return 0.
            else:
                return -(2 * y - 1 + r) / (1 - r ** 2) ** 2

        def g_1(y, r):
            if (y < 0 or y > 1 - r ** 2):
                return 0.
            else:
                return -(2 * y - 1 + r) * (1 - 2 * r) / (1 - r) ** 2 / (1 + 2 * r)

        def g_0(y, r):
            if (y < 0 or y > 1 - r ** 2):
                return 0.
            else:
                return 1 / (1 - r)

        def y_distribution(y):
            pi_term = branching[0] * (g_pi(y, rs[0]) + g_0(y, rs[0]))
            # rest_terms = branching[1:]*(g_1(y,rs)+g_0(y,rs))
            rest_terms = [ branch * (g_1(y, r) + g_0(y, r)) for branch, r in zip(branching[1:], rs[1:]) ]
            return pi_term + np.sum(rest_terms)

        chosen_y = rejection_sampling(y_distribution, 0, 1, 3)

        return 1 - chosen_y

    elif (branch == 'tau_e' or branch == 'tau_mu'):

        mu = tau_mass
        if (branch == 'tau_e'):
            m_l = e_mass
        elif (branch == 'tau_mu'):
            m_l = mu_mass

        nu_min = m_l
        nu_max = (mu ** 2 + m_l ** 2) / 2 / mu

        # Fraction energy distibution in the decaying particle rest frame
        def x_distribution(x):
            if (x < m_l / nu_max or x > 1):
                return 0.
            else:
                factor = G_F ** 2 * mu ** 5 / 192 / np.pi ** 3
                return factor * (3 - 2 * x) * x ** 2

        chosen_x = rejection_sampling(x_distribution, 0, 1, x_distribution(1))
        chosen_cos = rnd.uniform(-1, 1)

        y_rest = chosen_x * nu_max / tau_mass
        # Transforming the rest inelasticity to the lab inelasticity
        y_lab = y_rest - np.sqrt(y_rest ** 2 - (m_l / mu) ** 2) * chosen_cos

        return y_lab


def rejection_sampling(f, xmin, xmax, ymax, rnd=None):
    """
    Draws a random number following a given distribution using
    a rejection sampling algorithm.

    Parameters
    ----------
    f: function
        Random distribution
    xmin: float
        Minimum value of the argument
    xmax: float
        Maximum value of the argument
    ymax: float
        Maximum function value to use for the rejection sample
        (e.g., the maximum of the function)
    rnd: random generator object
        if None is provided, a new default random generator object is initialized

    Returns
    -------
    x: float
        Random value from the distribution
    """
    if(rnd is None):
        rnd = np.random.default_rng()
    reject = True

    while(reject):
        x = rnd.uniform(xmin, xmax)
        y = rnd.uniform(0, ymax)
        reject = f(x) < y

    return x
