import fc from 'fast-check';
import { describe, it, expect } from 'vitest';
import { fit, toScreen, toLogical, BOARD_ASPECT } from './viewport.js';

const TOL = 1e-9;

const posDim = fc.integer({ min: 100, max: 4000 });

describe('viewport transform', () => {
  // Feature: collaborative-cursor-scaffold, Property 12: Coordinate transform round-trip (toLogical ∘ toScreen ≈ identity)
  it('Property 12: round-trip toLogical(toScreen(l)) ≈ l', () => {
    fc.assert(
      fc.property(
        fc.double({ min: 0, max: 1, noNaN: true, noDefaultInfinity: true }),
        fc.double({ min: 0, max: 1, noNaN: true, noDefaultInfinity: true }),
        posDim,
        posDim,
        (lx, ly, vw, vh) => {
          const f = fit(vw, vh, BOARD_ASPECT);
          const l = [lx, ly];
          const back = toLogical(toScreen(l, f), f);
          return Math.abs(back[0] - l[0]) < TOL && Math.abs(back[1] - l[1]) < TOL;
        },
      ),
      { numRuns: 100 },
    );
  });

  // Feature: collaborative-cursor-scaffold, Property 13: toScreen maps the board rectangle exactly, and the fit is centered and within the viewport
  it('Property 13: board rect, aspect, centering, and cover-fits viewport', () => {
    fc.assert(
      fc.property(posDim, posDim, (vw, vh) => {
        const f = fit(vw, vh, BOARD_ASPECT);
        const tl = toScreen([0, 0], f);
        const br = toScreen([1, 1], f);
        const aspectOk = Math.abs((f.bw / f.bh) - BOARD_ASPECT) < TOL;
        const centerOk = Math.abs(f.ox - (vw - f.bw) / 2) < TOL
          && Math.abs(f.oy - (vh - f.bh) / 2) < TOL;
        const coverOk = f.bw >= vw - TOL && f.bh >= vh - TOL;
        const cornersOk = Math.abs(tl[0] - f.ox) < TOL && Math.abs(tl[1] - f.oy) < TOL
          && Math.abs(br[0] - (f.ox + f.bw)) < TOL && Math.abs(br[1] - (f.oy + f.bh)) < TOL;
        return aspectOk && centerOk && coverOk && cornersOk;
      }),
      { numRuns: 100 },
    );
  });

  // Feature: collaborative-cursor-scaffold, Property 14: toLogical clamping is total over any screen point
  it('Property 14: toLogical always returns [0,1] coordinates', () => {
    fc.assert(
      fc.property(
        fc.double({ noNaN: true, noDefaultInfinity: true }),
        fc.double({ noNaN: true, noDefaultInfinity: true }),
        posDim,
        posDim,
        (sx, sy, vw, vh) => {
          const f = fit(vw, vh, BOARD_ASPECT);
          const [lx, ly] = toLogical([sx, sy], f);
          return lx >= 0 && lx <= 1 && ly >= 0 && ly <= 1;
        },
      ),
      { numRuns: 100 },
    );
  });

  it('smoke: center logical maps to board center', () => {
    const f = fit(800, 600, BOARD_ASPECT);
    const [sx, sy] = toScreen([0.5, 0.5], f);
    expect(sx).toBeCloseTo(f.ox + f.bw / 2);
    expect(sy).toBeCloseTo(f.oy + f.bh / 2);
  });
});
