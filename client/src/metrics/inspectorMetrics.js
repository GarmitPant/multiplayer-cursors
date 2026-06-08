/** Dev inspector counters — hot-path increments only; sampled for display elsewhere. */

export function countRecvPositions(msg) {
  if (msg?.type === 'cursors') return msg.updates?.length ?? 0;
  if (msg?.type === 'cursor') return 1;
  return 0;
}

export function createInspectorMetrics() {
  return {
    sent: 0,
    recvMsgs: 0,
    recvPos: 0,
    recordSend() {
      this.sent += 1;
    },
    recordRecv(msg) {
      this.recvMsgs += 1;
      this.recvPos += countRecvPositions(msg);
    },
    resetWindow() {
      this.sent = 0;
      this.recvMsgs = 0;
      this.recvPos = 0;
    },
  };
}
