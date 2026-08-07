export const DEFAULT_APP_NAME = 'NyankoFace';

export function getAppName() {
  return process.env.APP_NAME?.trim() || DEFAULT_APP_NAME;
}
