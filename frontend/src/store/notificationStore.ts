import { create } from "zustand"

interface Notification {
  id: string
  title: string
  body: string
  read: boolean
  createdAt: string
}

interface NotificationState {
  notifications: Notification[]
  addNotification: (n: Omit<Notification, "id" | "read" | "createdAt">) => void
  markAllRead: () => void
  unreadCount: () => number
}

export const useNotificationStore = create<NotificationState>((set, get) => ({
  notifications: [],
  addNotification: (n) =>
    set((s) => ({
      notifications: [
        { ...n, id: Math.random().toString(36).slice(2), read: false, createdAt: new Date().toISOString() },
        ...s.notifications.slice(0, 49),
      ],
    })),
  markAllRead: () =>
    set((s) => ({ notifications: s.notifications.map((n) => ({ ...n, read: true })) })),
  unreadCount: () => get().notifications.filter((n) => !n.read).length,
}))
