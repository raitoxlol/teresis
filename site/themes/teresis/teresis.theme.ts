// The teresis theme. `astryx experimental theme editor` wrote this file once and never changes it again.
// The checked settings live in teresis.settings.json and the generated teresis.settings.ts;
// change them with `astryx experimental theme editor set teresis ...`. Add your own changes below: they win over the settings.
import {defineTheme} from '@astryxdesign/core/theme';
import {teresisSettings} from './teresis.settings';

export const teresisTheme = defineTheme({
  extends: teresisSettings,
  name: 'teresis',
});
