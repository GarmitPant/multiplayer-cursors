export function initials(name) {
  const parts = (name || '').trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }
  return (parts[0]?.slice(0, 2) || '?').toUpperCase();
}

export const AVATAR_MAX_VISIBLE = 5;

export function avatarSlice(users, maxVisible = AVATAR_MAX_VISIBLE) {
  const visible = users.slice(0, maxVisible);
  const overflow = Math.max(0, users.length - maxVisible);
  return { visible, overflow };
}
