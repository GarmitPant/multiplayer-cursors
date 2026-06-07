import { avatarSlice, initials } from '../lib/presence.js';
import { cursorUiColor } from '../lib/colors.js';
import './AvatarStack.css';

export default function AvatarStack({ users }) {
  const { visible, overflow } = avatarSlice(users);

  return (
    <div className="avatar-stack" aria-label={`${users.length} people on this Canvas`}>
      {visible.map((user, index) => {
        const uiColor = cursorUiColor(user.color);
        return (
          <span
            key={user.user_id}
            className="avatar-chip"
            style={{
              backgroundColor: uiColor,
              zIndex: visible.length - index,
            }}
            title={user.name}
          >
            {initials(user.name)}
          </span>
        );
      })}
      {overflow > 0 ? (
        <span className="avatar-overflow" title={`${overflow} more`}>
          +{overflow}
        </span>
      ) : null}
    </div>
  );
}
