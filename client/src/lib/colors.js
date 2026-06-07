/** Nudge light server palette entries for white-label UI contrast (trails keep server color). */
const UI_NUDGE = {
  '#84cc16': '#4d7c0f',
  '#06b6d4': '#0e7490',
  '#f59e0b': '#c2410c',
};

export function cursorUiColor(serverColor) {
  if (!serverColor) return '#333';
  return UI_NUDGE[serverColor.toLowerCase()] || serverColor;
}
