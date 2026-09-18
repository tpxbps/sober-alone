let atmosphere: Promise<typeof import('./fluidAtmosphere')> | undefined;

export function loadAtmosphere() {
  if (!atmosphere) {
    performance.mark('lobby:atmosphere-request');
    atmosphere = import('./fluidAtmosphere').then(module => {
      performance.mark('lobby:atmosphere-module');
      return module;
    }).catch(error => { atmosphere = undefined; throw error; });
  }
  return atmosphere;
}
