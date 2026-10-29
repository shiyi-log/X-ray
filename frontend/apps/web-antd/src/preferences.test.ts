import { overridesPreferences } from './preferences';

describe('X-ray application preferences', () => {
  it('enables the Vben update checker for deployed frontend bundles', () => {
    expect(overridesPreferences.app?.enableCheckUpdates).toBe(true);
  });
});
