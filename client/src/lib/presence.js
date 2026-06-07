export function initials(name) {
  const parts = (name || '').trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }
  return (parts[0]?.slice(0, 2) || '?').toUpperCase();
}

export const AVATAR_MAX_VISIBLE = 10;

export function mergePresenceRecord(prev, user) {
  if (!user?.user_id) return prev;
  return {
    user_id: user.user_id,
    name: user.name || prev?.name || 'Guest',
    color: user.color || prev?.color || '#333',
  };
}

export function upsertPresenceUser(list, user) {
  if (!user?.user_id) return list;
  const idx = list.findIndex((u) => u.user_id === user.user_id);
  const entry = mergePresenceRecord(idx >= 0 ? list[idx] : undefined, user);
  if (idx >= 0) {
    const next = [...list];
    next[idx] = { ...next[idx], ...entry };
    return next;
  }
  return [...list, entry];
}

export function removePresenceUser(list, userId) {
  return list.filter((u) => u.user_id !== userId);
}

export function presenceFromInit(self, peerList) {
  let list = [{ user_id: self.user_id, name: self.name, color: self.color }];
  for (const p of peerList || []) {
    list = upsertPresenceUser(list, p);
  }
  return list;
}

export function avatarSlice(users, maxVisible = AVATAR_MAX_VISIBLE) {
  const visible = users.slice(0, maxVisible);
  const overflow = Math.max(0, users.length - maxVisible);
  return { visible, overflow };
}
