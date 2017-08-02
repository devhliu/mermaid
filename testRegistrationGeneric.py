"""
This is a test implementation to see if we can use pyTorch to solve
LDDMM-style registration problems via automatic differentiation.

Contributors:
  Marc Niethammer: mn@cs.unc.edu
"""

# Note: all images have to be in the format BxCxXxYxZ (BxCxX in 1D and BxCxXxY in 2D)
# I.e., in 1D, 2D, 3D we are dealing with 3D, 4D, 5D tensors. B is the batchsize, and C are the channels
# (for example to support color-images or general multi-modal registration scenarios)

# first do the torch imports
from __future__ import print_function
import torch
from torch.autograd import Variable
import time

import numpy as np

import set_pyreg_paths

from pyreg import utils

import pyreg.visualize_registration_results as vizReg
import pyreg.example_generation as eg
import pyreg.module_parameters as pars

import pyreg.model_factory as MF
import pyreg.smoother_factory as SF
import pyreg.custom_optimizers as CO

# load settings from file
loadSettingsFromFile = True
saveSettingsToFile = True

# select the desired dimension of the registration
useMap = True# set to true if a map-based implementation should be used
visualize = True # set to true if intermediate visualizations are desired
smoothImages = True
useRealImages = False
nrOfIterations = 20 # number of iterations for the optimizer
#modelName = 'SVF'
modelName = 'LDDMMShooting'
#modelName = 'LDDMMShootingScalarMomentum'
dim = 2

# general parameters
mp = pars.ModuleParameters()
if loadSettingsFromFile:
    settingFile = modelName + '_settings.json'
    print( 'Reading settings from: ' + settingFile )
    mp.loadJSON( settingFile )

params = mp.getRoot()

torch.set_num_threads(4) # not sure if this actually affects anything
print('Number of pytorch threads set to: ' + str(torch.get_num_threads()))

if useRealImages:

    I0,I1= eg.CreateRealExampleImages(dim).create_image_pair()

else:
    szEx = np.tile( 50, dim )         # size of the desired images: (sz)^dim

    cc = pars.setCurrentCategory(params,'square_example_images')
    pars.setCurrentKey(cc,'len_s', szEx.min()/6)
    pars.setCurrentKey(cc,'len_l', szEx.max()/4)

    # create a default image size with two sample squares
    I0,I1= eg.CreateSquares(dim).create_image_pair(szEx,params)

sz = np.array(I0.shape)

assert( len(sz)==dim+2 )

# spacing so that everything is in [0,1]^2 for now
spacing = 1./(sz[2::]-1) # the first two dimensions are batch size and number of image channels
print ('Spacing = ' + str( spacing ) )

# some settings for the registration energy
# Reg[\Phi,\alpha,\gamma] + 1/\sigma^2 Sim[I(1),I_1]

# All of the following manual settings can be removed if desired
# they will then be replaced by their default setting

mf = MF.ModelFactory( sz, spacing )

model,criterion = mf.createRegistrationModel( modelName, useMap, params)
print(model)

# create the source and target image as pyTorch variables
ISource = Variable( torch.from_numpy( I0.copy() ), requires_grad=False )
ITarget = Variable( torch.from_numpy( I1 ), requires_grad=False )

if smoothImages:
    # smooth both a little bit
    cc = pars.setCurrentCategory(params,'image_smoothing')
    ccs = pars.setCurrentCategory(cc,'smoother')
    pars.setCurrentKey(ccs,'type','gaussian')
    pars.setCurrentKey(ccs,'gaussianStd',0.05)
    s = SF.SmootherFactory( sz[2::], spacing ).createSmoother(cc)
    ISource = s.computeSmootherScalarField(ISource)
    ITarget = s.computeSmootherScalarField(ITarget)

if useMap:
    # create the identity map [-1,1]^d, since we will use a map-based implementation
    id = utils.identityMap_multiN(sz)
    identityMap = Variable( torch.from_numpy( id ), requires_grad=False )

# use LBFGS as optimizer; this is essential for convergence when not using the Hilbert gradient
#optimizer = torch.optim.LBFGS(model.parameters(),
#                              lr=1,max_iter=1,max_eval=5,
#                              tolerance_grad=1e-3,tolerance_change=1e-4,
#                              history_size=5)

optimizer = CO.LBFGS_LS(model.parameters(),
                              lr=1.0,max_iter=1,max_eval=5,
                              tolerance_grad=1e-3,tolerance_change=1e-4,
                              history_size=5,line_search_fn='backtracking')

# optimize for a few steps
start = time.time()

for iter in range(nrOfIterations):

    def closure():
        optimizer.zero_grad()
        # 1) Forward pass: Compute predicted y by passing x to the model
        # 2) Compute loss
        if useMap:
            phiWarped = model(identityMap, ISource)
            loss = criterion(phiWarped, ISource, ITarget)
        else:
            IWarped = model(ISource)
            loss = criterion(IWarped, ISource, ITarget)

        loss.backward()
        return loss

    # take a step of the optimizer
    optimizer.step(closure)

    # apply the current state to either get the warped map or directly the warped source image
    if useMap:
        phiWarped = model(identityMap, ISource)
    else:
        cIWarped = model(ISource)

    if iter%1==0:
        if useMap:
            energy, similarityEnergy, regEnergy = criterion.getEnergy(phiWarped, ISource, ITarget)
        else:
            energy, similarityEnergy, regEnergy = criterion.getEnergy(cIWarped, ISource, ITarget)

        print('Iter {iter}: E={energy}, similarityE={similarityE}, regE={regE}'
              .format(iter=iter,
                      energy=utils.t2np(energy),
                      similarityE=utils.t2np(similarityEnergy),
                      regE=utils.t2np(regEnergy)))

    if visualize:
        if iter%5==0:
            if useMap:
                I1Warped = utils.computeWarpedImage_multiNC(ISource,phiWarped)
                vizReg.showCurrentImages(iter, ISource, ITarget, I1Warped, phiWarped)
            else:
                vizReg.showCurrentImages(iter, ISource, ITarget, cIWarped)

print('time:', time.time() - start)

if saveSettingsToFile:
    mp.writeJSON(modelName + '_settings_clean.json')
    mp.writeJSONComments(modelName + '_settings_comments.json')