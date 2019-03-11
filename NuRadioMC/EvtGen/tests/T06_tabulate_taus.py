from NuRadioMC.EvtGen.generator import *

filename = 'decay_library.hdf5'
fout = h5py.File(filename, 'w')

times = np.linspace(1e-3*tau_rest_lifetime, 10*tau_rest_lifetime, 100)
energies = np.linspace(15, 20, 100)
energies = 10**energies * units.eV

# "Clever" way of looping. However, we don't see the progress with this.
#tables = [ [ get_decay_time_losses(energy, 1000*units.km, average=True, compare=True, user_time=time)
#            for time in times ] for energy in energies ]

tables = []
for energy in energies:
    row = []
    for time in times:
        print(np.where(energies==energy)[0], np.where(times==time)[0])
        row.append( get_decay_time_losses(energy, 1000*units.km, average=True, compare=False, user_time=time) )
    tables.append(row)

tables = np.array(tables)

fout['decay_times'] = tables[:,:,0]
fout['decay_energies'] = tables[:,:,1]
fout['rest_times'] = times
fout['initial_energies'] = energies

print(tables[:,:,0])
print(tables[:,:,1])

fout.close()
