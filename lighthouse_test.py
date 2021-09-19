import numpy as np
import model
from NestedSampling import NestedSampler
import matplotlib.pyplot as plt
plt.rc('font', size=12)
plt.rc('font', family='serif')

class lighthouse_model(model.Model):

      def set_parameters(self,data):
          self.bounds = ([-10,0], [10,10])
          self.names  = ['a', 'b']
          self.data   = data

      @model.Model.auto_bound
      def log_prior(self,vars):
          return 0

      @model.Model.varenv
      def log_likelihood(self,vars):
          u = np.zeros(vars.shape)
          for i in range(len(self.data)):
              u += np.log(vars['b']) - np.log(vars['b']**2 + (self.data[i] - vars['a'])**2)
          return u

x_observations = np.array([-9.8,-8.5,9.1,9.9,7.4,-6.])
model_         = lighthouse_model(x_observations)
ns             = NestedSampler(model_, nlive = 1000, evosteps = 1000, load_old=True, filename = 'lighthouse.nkn')

ns.run()
print(ns.Z, ns.Z_error)

fig, scat = plt.subplots()
scat.scatter(ns.points['position']['a'],ns.points['position']['b'], c = np.exp(ns.points['logL']), cmap='plasma')
scat.scatter(x_observations, x_observations*0, color = (0,1,0), s = 30, marker = '<')
scat.set_title(f'Lighthouse problem ({len(ns.points)} samples in {ns.run_time:.0f} s)')




plt.show()
