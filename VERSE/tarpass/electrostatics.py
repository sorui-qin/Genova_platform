# Gaussian overlap implementation from TarPass / hesther/espsim.
import numpy as np

def GaussInt(dist,
             charge1,
             charge2,
):
    """Calculates the analytic Gaussian integrals.
    :param dist: Distance matrix.
    :param charge1: 1D array of partial charges of first molecule.
    :param charge2: 1D array of partial charges of second molecule.
    :return: Analytic overlap integral.
    """

    #These are precomputed coefficients:
    a=np.array([[ 15.90600036,   3.9534831 ,  17.61453176],
                [  3.9534831 ,   5.21580206,   1.91045387],
                [ 17.61453176,   1.91045387, 238.75820253]])
    b=np.array([[-0.02495   , -0.04539319, -0.00247124],
                [-0.04539319, -0.2513    , -0.00258662],
                [-0.00247124, -0.00258662, -0.0013    ]])

    a_flat = a.flatten() 
    b_flat = b.flatten()
    dist = (dist**2).flatten()
    charges = (charge1[:,None]*charge2).flatten() #pairwise products of atomic charges, flattened 
    return ((a_flat[:,None] * np.exp(dist * b_flat[:,None])).sum(0) * charges).sum()


