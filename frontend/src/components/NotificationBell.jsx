import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { Bell } from 'lucide-react';
import { API_URL } from '../constants';
import { NOTIFICATIONS } from '../constants/testIds';
import { Popover, PopoverTrigger, PopoverContent } from './ui/popover';

/* ─────────────────────────────────────────────────────────────────────
   Notification bell - Phase 4 Step 4.4 of the EYV Agent System roadmap.

   Sourced from GET /api/notifications (new in this step - wraps
   notification_service.list_notifications/count_unread_notifications,
   Step 4.3), which returns both the unread count and the list in one
   call. Uses the existing Radix-based Popover component (components/ui/popover.jsx)
   for the dropdown rather than a hand-rolled panel, matching how this
   library is already used elsewhere.

   "Opening/viewing marks them read": as soon as the popover opens (not on
   a per-notification click), this calls PATCH /api/notifications/read
   (new in this step - wraps notification_service.mark_notifications_read,
   also new in this step, additive only - see that function's own
   docstring) and optimistically clears the badge/marks every currently-
   shown notification read locally, so there's no flash of a stale count
   between the click and the response.
───────────────────────────────────────────────────────────────────── */

function timeAgo(isoString) {
  const then = new Date(isoString).getTime();
  const diffMinutes = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (diffMinutes < 1) return 'just now';
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${Math.round(diffHours / 24)}d ago`;
}

const STATUS_LABEL = {
  implemented: 'Fixed',
  rejected: 'Not moving forward',
  backlog: 'Backlog',
};

export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);

  const fetchNotifications = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API_URL}/notifications`, { withCredentials: true });
      setNotifications(data.notifications);
      setUnreadCount(data.unread_count);
    } catch (error) {
      // Silent - a failed notification fetch shouldn't interrupt whatever
      // page this bell is floating on top of.
    }
  }, []);

  useEffect(() => {
    fetchNotifications();
  }, [fetchNotifications]);

  const handleOpenChange = async (isOpen) => {
    setOpen(isOpen);
    if (!isOpen || unreadCount === 0) return;

    // Optimistic - the badge clears the moment the list opens, not after
    // the PATCH round-trip.
    setUnreadCount(0);
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
    try {
      await axios.patch(`${API_URL}/notifications/read`, {}, { withCredentials: true });
    } catch (error) {
      // Re-sync from the server rather than leaving an optimistic state
      // that might not have actually landed.
      fetchNotifications();
    }
  };

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <button
          data-testid={NOTIFICATIONS.bellButton}
          // top-20 (not top-4) - clears every page's own sticky top-0 z-50
          // header (see e.g. DashboardPage.jsx's <motion.header>, ~4.5rem
          // tall with its own logout button near this same corner) rather
          // than sitting underneath it and having clicks intercepted.
          className="fixed top-20 right-4 z-40 bg-white text-[#1C1917] p-3 rounded-full shadow-lg border border-[#E7E5E4] hover:shadow-xl transition-shadow"
          aria-label="Notifications"
        >
          <Bell size={20} />
          {unreadCount > 0 && (
            <span
              data-testid={NOTIFICATIONS.unreadBadge}
              className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-semibold flex items-center justify-center"
            >
              {unreadCount > 9 ? '9+' : unreadCount}
            </span>
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0" data-testid={NOTIFICATIONS.list}>
        <div className="px-4 py-3 border-b border-[#E7E5E4]">
          <h3 className="font-semibold text-sm text-[#1C1917]">Notifications</h3>
        </div>
        <div className="max-h-96 overflow-y-auto">
          {notifications.length === 0 ? (
            <p className="px-4 py-6 text-sm text-[#78716C] text-center">No notifications yet.</p>
          ) : (
            notifications.map((n) => (
              <div
                key={n.id}
                data-testid={NOTIFICATIONS.item}
                className={`px-4 py-3 border-b border-[#F0EEEA] last:border-b-0 ${n.read ? '' : 'bg-[#FEF3E8]'}`}
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="text-xs font-medium text-[#C47245]">
                    {STATUS_LABEL[n.status] || n.status}
                  </span>
                  <span className="text-[10px] text-[#A8A29E] shrink-0">{timeAgo(n.created_at)}</span>
                </div>
                <p className="text-sm text-[#1C1917] mt-0.5">{n.title}</p>
                <p className="text-xs text-[#78716C] mt-0.5">{n.body}</p>
              </div>
            ))
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
