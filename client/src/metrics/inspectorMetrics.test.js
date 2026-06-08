import { describe, expect, it } from 'vitest';
import {
  countRecvPositions,
  createInspectorMetrics,
} from './inspectorMetrics.js';

describe('inspectorMetrics', () => {
  it('counts a single cursor frame as 1 msg and 1 position', () => {
    const m = createInspectorMetrics();
    m.recordRecv({ type: 'cursor', p: [0.5, 0.5] });
    expect(m.recvMsgs).toBe(1);
    expect(m.recvPos).toBe(1);
  });

  it('counts a batched cursors frame as 1 msg and N positions', () => {
    const m = createInspectorMetrics();
    m.recordRecv({
      type: 'cursors',
      updates: [{ user_id: 'a' }, { user_id: 'b' }, { user_id: 'c' }],
    });
    expect(m.recvMsgs).toBe(1);
    expect(m.recvPos).toBe(3);
  });

  it('does not count draw frames toward recv positions', () => {
    const m = createInspectorMetrics();
    m.recordRecv({ type: 'draw', seq: 1, pts: [[0.1, 0.2]] });
    expect(m.recvMsgs).toBe(1);
    expect(m.recvPos).toBe(0);
    expect(countRecvPositions({ type: 'draw' })).toBe(0);
  });

  it('tracks sent messages separately from receive', () => {
    const m = createInspectorMetrics();
    m.recordSend();
    m.recordSend();
    m.recordRecv({ type: 'cursor', p: [0.5, 0.5] });
    expect(m.sent).toBe(2);
    expect(m.recvMsgs).toBe(1);
    m.resetWindow();
    expect(m.sent).toBe(0);
    expect(m.recvMsgs).toBe(0);
    expect(m.recvPos).toBe(0);
  });
});
