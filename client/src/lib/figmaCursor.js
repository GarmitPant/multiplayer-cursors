import { cursorUiColor } from './colors.js';

const ARROW_PATH = 'M1 1v14l3.5-3.5L8 17l2-1-3.5-6H12L1 1z';

export function createFigmaCursorElement(color, name) {
  const uiColor = cursorUiColor(color || '#333');
  const el = document.createElement('div');
  el.className = 'figma-cursor';

  const arrow = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  arrow.setAttribute('class', 'figma-cursor-arrow');
  arrow.setAttribute('width', '17');
  arrow.setAttribute('height', '19');
  arrow.setAttribute('viewBox', '0 0 17 19');
  arrow.setAttribute('aria-hidden', 'true');
  arrow.style.color = uiColor;

  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', ARROW_PATH);
  path.setAttribute('fill', 'currentColor');
  path.setAttribute('stroke', '#ffffff');
  path.setAttribute('stroke-width', '1.2');
  path.setAttribute('stroke-linejoin', 'round');
  arrow.appendChild(path);

  const label = document.createElement('span');
  label.className = 'figma-cursor-label';
  label.style.backgroundColor = uiColor;
  label.textContent = name || '';

  el.appendChild(arrow);
  el.appendChild(label);

  return { el, label, uiColor };
}

export function applyFigmaCursorIdentity(cursorParts, color, name) {
  if (!cursorParts) return;
  const uiColor = cursorUiColor(color || cursorParts.uiColor || '#333');
  cursorParts.uiColor = uiColor;
  cursorParts.label.style.backgroundColor = uiColor;
  cursorParts.el.querySelector('.figma-cursor-arrow').style.color = uiColor;
  if (name) cursorParts.label.textContent = name;
}
