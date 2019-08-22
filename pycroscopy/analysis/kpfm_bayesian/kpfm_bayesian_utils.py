# Oak Ridge National Lab
# Center for Nanophase Materials Sciences
# written by Alvin Tan on 08/06/2019
# in collaboration with Rama Vasudevan, Liam Collins, and Kody Law

# This program provides the Pycroscopy framework to process messy, noisy data streamed in from a fundamentally
# new data acquisition method incepted by Liam and involving Kelvin probe microscopy.

# Disclaimer: This code is written with little information on what the various variables are, so some massaging may
# be necessary.


from matplotlib import pyplot as plt
import scipy.optimize as spo
import scipy.linalg as spla
import numpy as np
import time


# Not entirely sure what Rforce is. From what I understand, it's the original clean signal that we are trying
# to reconstruct by processing R_H, but that may be incorrect. In that case, we might not actually want it as
# an input for this function.
def process_pixel(R_H, wd, p, Rforce=None, graph=False, verbose=False):
	# Run Bayesian inference on the data
	if verbose: print("Starting Bayesian inference...")
	y, tt, pp1, sig, gam, AA, B, BB, CC, C0, P0, CC1, GAI, M, m0, phi, m_phi, Sig = _BayesianInference(R_H, wd, p, verbose=verbose)

	# Then process the results into data we want to store
	if verbose: print("Finished Bayesian inference. Starting processing of results...")
	return _processResults(p, R_H, wd, Rforce, M, Sig, B, m_phi, y, CC, graph=graph, verbose=verbose)


# Returns the default parameter dictionary for an NC-AFM setup.
# This instantiation is from the simulation code (RunSimulations_SNRnoiseLooping.m) but most of the values are
# from the physical properties of the measurement setup.
def get_default_parameters():
	p = {}

	# detection and excitation system parameters
	p['SYS.dzds'] = 81e-15 	# Detection system noise 
							# amplitude spectral density d_ds^z in m/sqHz
	             
	p['SYS.INVOLS'] = 52.5e-9	# Sensitivity of detection system in m/V

	# Cantilever parameters
	p['CL.f0'] = 58e3 		# resonance frequency in Hz
	p['CL.Q'] = 115 		# quality factor (unitless)
	p['CL.k'] = 2.8 		# cantilever stiffness in N/m
	p['CL.A'] = 1 			# amplitude (zero-peak) in m
	p['CL.T'] = 273.15+23.8 # CL temperature in K
	p['CL.f1'] = 350e3 		# 2nd Eig resonance frequency in Hz
	p['CL.Q1'] = 350 		# 2nd Eig quality factor (unitless)
	p['CL.A1'] = 0.0000 	# 2nd Eig amplitude (zero-peak) in m

	# Tip geometry
	p['Tip.c_angle'] = 32*np.pi/180 	# Cone angle of probe
	p['TS.Rtip'] = 20e-9 				# Radius of probe apex (m)
	p['TS.Rheight'] = 22e-6 			# Height of probe (i.e. distance from tip apex to cantilever) (m)
	p['TS.eps_z'] = 8.85e-12 			# permitivity

	# tip-sample interaction
	p['TS.alpha'] = -12.3e9 # alpha_ts in Hz/m
	p['TS.beta'] = 12.3e9 	# beta_ts in Hz/m

	# Data Simulation Parameters
	p['Sim.Tmax'] = 4.096e-3*2 	# simulation time (s)
	p['Sim.IOrate'] = 4e6 		# Sampling rate (Hz)
	p['Sim.Vfreq'] = 56e3 		# AC voltage Drive Frequency (Hz)
	p['Sim.VAmp'] = 3 			# AC voltage Drive Amplitude (p2p)
	p['Sim.VCPD'] = -1			# AC voltage Drive Amplitude (p2p)
	p['Sim.VDC'] = 0
	p['Sim.Phasshift'] = 0.2 	## Some noise
	p['Sim.NAmp'] = 1e-6 		## Some noise
	p['Sim.snr'] = 12

	# Bayesian Parameters
	p['Bayes.fac'] = 128 	# factor to reduce length of timeseries
	p['Bayes.Npoly'] = 2
	p['Bayes.aa'] = 2 		##hyperparameters

	return p


# You probably have a better idea of what this does than I do.
def _B_phin(phi, w, tt, n):
	'''
	phi is a number
	w is a number
	tt is a numpy column vector
	n is probably a number
	'''
	N = tt.size
	Bn = np.zeros((2*N, n+1))

	for i in range(n+1):
		Bn[1:2*N+1:2, i] = np.squeeze(np.sin(w*tt + phi)**i)

	return Bn


# Same with this one.
# This seems to be used as a cost function, though, and is minimized during the Bayesian inference algorithm.
def _mmlenn(pp, w, tt, AA, a1, a2, y, n, M, h, m0, sigi, aa):
	'''
	pp is a row vector
	w is a constant
	tt is a column vector
	AA is a square matrix
	a1 and a2 are unclear
	y is a numpy column vector
	n is a number?
	M is a number?
	h is a number
	m0 is a column vector
	sigi is probably a number
	aa is something
	'''

	phi = pp[2]
	sig = pp[0]
	gam = pp[1]
	N = y.size
	P0 = np.diag(np.concatenate((np.array([1/sigi/sigi, 1/sigi/sigi]), 1/sig/sig*(np.arange(1, n+2)**aa))))
	C0 = np.linalg.inv(P0)
	GAI = 1/gam/gam*np.eye(N)

	B = _B_phin(phi, w, tt, n)
	BB = np.matmul(AA, B)*h
	CC1 = np.concatenate((a1.reshape((a1.size, 1), order='F'),
						  a2.reshape((a2.size, 1), order='F'), BB), axis=1)
	CC = CC1[::2, :]

	Sig, resid, rank, s = np.linalg.lstsq(P0 + np.matmul(np.matmul(CC.T, GAI), CC), np.eye(M), rcond=None)
	m_phi = np.matmul(Sig, np.matmul(np.matmul(CC.T, GAI), y) + np.matmul(P0, m0))

	if (-np.pi <= phi) and (phi <= 0):
		out = np.sum(np.log(gam**2*np.ones((N, 1)))) + np.sum(np.log(np.linalg.eig(Sig)[0])) + \
			  np.matmul(np.matmul(y.T, GAI), y) - np.matmul(np.matmul(np.matmul(Sig, CC.T), np.matmul(GAI, y)).T, np.matmul(np.matmul(CC.T, GAI), y)) + 0*sig**2/200 # what is the point of this 0*...
		out = float(out)
	else:
		out = np.inf

	return out


# This runs the actual Bayesian inference, which is a lot of statistics.
def _BayesianInference(R_H, wd, p, verbose=False):
	'''
	R_H is a numpy row vector
	wd is a number
	p is a dictionary
	'''
	fac = p["Bayes.fac"]
	Qi = 1/p["CL.Q"]
	OmV = wd*(1e-3)
	Om0 = p["CL.f0"]*(1e-3)
	w = OmV/Om0
	L = np.array([[0, 1], [-1, -Qi]])
	wr1 = p["CL.f0"]

	N = int(R_H.size/fac)

	T=p["Sim.Tmax"]*wr1*2*np.pi/fac

	R_H = R_H - np.mean(R_H)

	y = (1e9)*R_H[:N][np.newaxis].T
	A = np.zeros((2, 2*N))
	AA = np.zeros((2*N, 2*N))
	h = T/N
	tt = np.arange(T, step=h)[np.newaxis].T

	if verbose: startTime = time.time()

	for i in range(N):
		A[:, 2*i:2*(i+1)] = spla.expm(L*h*(i+1))

	a1 = np.fliplr(A[:, ::2])
	a2 = np.fliplr(A[:, 1::2])
	A1 = 0*A
	A1[:, ::2] = a1
	A1[:, 1::2] = a2

	for j in range(1, N):
		AA[2*j:2*(j+1), :2*j] = A1[:, -2*j:]

	a1 = A[:, ::2]
	a2 = A[:, 1::2]

	if verbose:
		prelim_time = time.time() - startTime
		print("Preliminary time is {} seconds".format(prelim_time))

	# Hyperparameters
	n = p["Bayes.Npoly"]
	M = 2+n+1;
	sigi = 3;
	sig = 1;
	gam = 0.1
	phi = 1
	aa = p["Bayes.aa"]

	P0 = np.diag(np.concatenate((np.array([1/sigi/sigi, 1/sigi/sigi]), 1/sig/sig*(np.arange(1, n+2)**aa))))
	C0 = np.linalg.inv(P0)
	GAI = 1/gam/gam*np.eye(N)

	m0 = np.concatenate((np.array([y[0] - (y[1]-y[0])]),
						 np.array([(y[1] - y[0])/h]),
						 np.zeros((n+1, 1))),
						axis=0)

	if verbose: startTime = time.time()

	B = _B_phin(phi, w, tt, n)
	BB = np.matmul(AA, B)*h

	CC1 = np.concatenate((a1.reshape((a1.size, 1), order='F'),
						  a2.reshape((a2.size, 1), order='F'), BB), axis=1)
	CC = CC1[::2, :]

	# Use np.linalg.lstsq for Matlab's left divide
	Sig, resid, rank, s = np.linalg.lstsq(P0 + np.matmul(np.matmul(CC.T, GAI), CC), np.eye(M), rcond=None)
	m_phi = np.matmul(Sig, np.matmul(np.matmul(CC.T, GAI), y) + np.matmul(P0, m0))

	rrmse = np.linalg.norm(y - np.matmul(CC, m_phi))/np.linalg.norm(y)

	if verbose:
		forward_time = time.time() - startTime
		print("Forward time is {} seconds".format(forward_time))

	# Optimize hyperparameters
	sd = 1
	np.random.seed(sd)

	pp0 = np.zeros(3)
	pp0[:2] = np.random.randn(1, 2)**2 
	pp0[2] = -np.pi*np.random.rand()

	# Blackbox optimization over Phi(theta; y)
	if verbose: startTime = time.time()
	optResult = spo.minimize(lambda pp: _mmlenn(pp, w, tt, AA, a1, a2, y, n, M, h, m0, sigi, aa), pp0)
	if verbose:
		optim_time_mle = time.time() - startTime
		print("First optimization time is {} seconds".format(optim_time_mle))

	fvalg = optResult.fun
	pp1g = optResult.x

	for i in range(10):
		pp0[:2] = np.random.randn(1, 2)**2
		pp0[2] = -np.pi*np.random.rand()

		if verbose: startTime = time.time()
		optResult = spo.minimize(lambda pp: _mmlenn(pp, w, tt, AA, a1, a2, y, n, M, h, m0, sigi, aa), pp0,
								 options={"maxiter":int(1e12)}, tol=1e-18)
		if verbose:
			optim_time_mle = time.time() - startTime
			print("Next optimization time is {} seconds".format(optim_time_mle))

		if optResult.fun < fvalg:
			pp1g = optResult.x
			fvalg = optResult.fun

	pp1 = pp1g

	if verbose: startTime = time.time()

	phi = pp1[2]
	sig = pp1[0]
	gam = pp1[1]
	B = _B_phin(phi, w, tt, n)
	BB = np.matmul(AA, B)*h 
	CC1 = np.concatenate((a1.reshape((a1.size, 1), order='F'),
						  a2.reshape((a2.size, 1), order='F'), BB), axis=1)
	CC = CC1[::2, :]
	P0 = np.diag(np.concatenate((np.array([1/sigi/sigi, 1/sigi/sigi]), 1/sig/sig*(np.arange(1, n+2)**aa))))

	C0 = np.linalg.inv(P0)
	GAI = 1/gam/gam*np.eye(N)

	Sig, resid, rank, s = np.linalg.lstsq(P0 + np.matmul(np.matmul(CC.T, GAI), CC), np.eye(M), rcond=None)#, rcond=-1)
	m_phi = np.matmul(Sig, np.matmul(np.matmul(CC.T, GAI), y) + np.matmul(P0, m0))

	if verbose: print("Post Bayesian data processing took {} seconds".format(time.time() - startTime))

	# Not all of these values seem important. I recommend revising these (and the computations done above) to clean it up a bit
	return y, tt, pp1, sig, gam, AA, B, BB, CC, C0, P0, CC1, GAI, M, m0, phi, m_phi, Sig


# This takes in the results from _BayesianInference and either returns a couple graphs or the return values we "want to save" in
# result datasets. This will have to be changed when the values deemed important are made more clear.
def _processResults(p, R_H, wd, Rforce, M, Sig, B, m_phi, y, CC, graph=False, verbose=False):
	t_max = p["Sim.Tmax"]
	fac = p["Bayes.fac"]
	wr1 = p["CL.f0"]
	Vac = p["Sim.VAmp"]
	phi = p["Sim.Phasshift"]
	n0 = 1000
	N1 = int(R_H.size/fac)
	OmV = wd*(1e-3)		# Drive frequency (kHz)
	Om0 = wr1*(1e-3)	# Resonance frequency (kHz)
	w = OmV/Om0			# Frequency normalized

	T = t_max*wr1*2*np.pi/fac	# Total time per section considered
	Tsec = p["Sim.Tmax"]/fac

	h = T/N1 	# Sampling rate
	tt = np.arange(T, step=h)[np.newaxis].T

	h1 = Tsec/N1 	# Total time
	tt1 = np.arange(Tsec, step=h1)[np.newaxis].T

	w_ang = wd*2*np.pi 

	# Rforce is generated by simulated data, I believe, so Rforce will be None with any actual data.
	if Rforce is not None:
		R = Rforce - np.mean(Rforce)
		R_seg = R[n0+1:n0+N1+1]*(1e9)
	else:
		R_seg = np.full(N1, np.nan)

	# We will want graphs when running test()
	if graph:
		# Let's try the 3D plot...
		from mpl_toolkits import mplot3d
		threeDboi = plt.figure()
		ax = plt.axes(projection='3d')

		sqrtBoi2 = np.sqrt(np.diag(Sig[2:M+1, 2:M+1]))
		ax.plot3D(Vac*np.sin(w*tt + phi).flatten(),
				  Vac*w_ang*np.cos(w_ang*tt1 + phi).flatten(),
				  np.matmul(B[1::2, :], m_phi[2:M+1]).flatten())
		ax.plot3D(Vac*np.sin(w*tt + phi).flatten(),
				  Vac*w_ang*np.cos(w_ang*tt1 + phi).flatten(),
				  np.matmul(B[1::2, :], m_phi[2:M+1] + sqrtBoi2[np.newaxis].T).flatten(), "r--")
		ax.plot3D(Vac*np.sin(w*tt + phi).flatten(),
				  Vac*w_ang*np.cos(w_ang*tt1 + phi).flatten(),
				  np.matmul(B[1::2, :], m_phi[2:M+1] - sqrtBoi2[np.newaxis].T).flatten(), "r--")
		ax.plot3D(Vac*np.sin(w_ang*tt1 + phi).flatten(),
				  Vac*w_ang*np.cos(w_ang*tt1 + phi).flatten(),
				  R_seg, "g")
		ax.set_xlabel("V_B")
		ax.set_ylabel("dV_B/dt")
		ax.set_zlabel("RHS F")
		#plt.legend()
		threeDboi.set_size_inches(8, 6)
		if verbose: threeDboi.show()

		# Then put everything else in the same graph for better storage
		bigFig = plt.figure()

		# Plot V_B vs F(V_B)
		plt.subplot(151)
		sqrtBoi = np.sqrt(np.diag(np.matmul(np.matmul(B[1::2, :], Sig[2:M+1, 2:M+1]), B[1::2, :].T)))
		plt.plot(Vac*np.sin(w_ang*tt1 + phi), np.matmul(B[1::2, :], m_phi[2:M+1]), label="V_B")
		plt.plot(Vac*np.sin(w_ang*tt1 + phi), np.matmul(B[1::2, :], m_phi[2:M+1]) + sqrtBoi[np.newaxis].T, "r--")
		plt.plot(Vac*np.sin(w_ang*tt1 + phi), np.matmul(B[1::2, :], m_phi[2:M+1]) - sqrtBoi[np.newaxis].T, "r--")
		plt.plot(Vac*np.sin(w_ang*tt1 + phi), R_seg, 'k')
		plt.xlabel("V_B")
		plt.ylabel("RHS F")
		plt.title("V_B vs F(V_B)")
		plt.legend()

		# Plot residual f_rec - R
		plt.subplot(152)
		plt.plot(tt1, R_seg, "r.")
		plt.plot(tt1 + (phi/w_ang), np.matmul(B[1::2, :], m_phi[2:M+1]), "k.")
		plt.xlabel("t")
		plt.ylabel("residual")
		plt.title("Residual f_rec - R")

		plt.subplot(153)
		plt.plot(tt1, y)
		plt.plot(tt1, np.matmul(CC, m_phi))
		plt.xlabel("t")
		plt.ylabel("residual")

		# Plot residual z_rec - y
		plt.subplot(154)
		plt.plot(tt1, y-np.matmul(CC, m_phi))
		plt.xlabel("t")
		plt.ylabel("residual")
		plt.title("Residual z_rec - y")

	# Do some more data maths
	rrmse = np.linalg.norm(y - np.matmul(CC, m_phi))/np.linalg.norm(y)
	x1 = Vac * np.sin(w_ang*tt1 + phi)
	y1 = np.matmul(B[1::2, :], m_phi[2:M+1])

	p1 = np.polyfit(x1.T[0], y1, 2)
	yfit = np.polyval(p1, x1)
	yresid = y1 - yfit
	SSresid = sum(yresid**2)
	SStotal = (y1.size - 1)*np.var(y1)
	rsq = 1 - SSresid/SStotal

	if graph:
		# another plot
		plt.subplot(155)
		plt.plot(x1, y1, "o", label="Recovered Force")
		plt.plot(x1, yfit, "-", label="Polynomial Fit")
		plt.legend()

		bigFig.set_size_inches(50, 6)
		if verbose: bigFig.show()

		# If we want graphs, we return two graphs: one 3D graph and one with 5 subplots.
		return threeDboi, bigFig

	# Otherwise, we return some values that are important enough to be stored in results datasets.
	return rrmse, np.matmul(B[1::2, :], m_phi[2:M+1]), R_seg, y - np.matmul(CC, m_phi), p1, float(rsq)









