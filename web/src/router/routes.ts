import type { RouteRecordRaw } from 'vue-router'

/** 页面组件一律懒加载:首屏只加载当前路由需要的代码。 */
export const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/features/auth/LoginPage.vue'),
    meta: { public: true },
  },
  {
    path: '/legal/agreement',
    name: 'legal-agreement',
    component: () => import('@/features/legal/LegalPage.vue'),
    props: { kind: 'agreement' },
    meta: { public: true },
  },
  {
    path: '/legal/privacy',
    name: 'legal-privacy',
    component: () => import('@/features/legal/LegalPage.vue'),
    props: { kind: 'privacy' },
    meta: { public: true },
  },
  {
    path: '/mobile-guard',
    name: 'mobile-guard',
    component: () => import('@/layouts/MobileGuard.vue'),
    meta: { public: true },
  },
  {
    path: '/banned',
    name: 'banned',
    component: () => import('@/features/shell/BannedPage.vue'),
    meta: { public: true },
  },
  {
    path: '/onboarding',
    name: 'onboarding',
    component: () => import('@/features/onboarding/OnboardingPage.vue'),
  },
  {
    path: '/home',
    component: () => import('@/layouts/DesktopShell.vue'),
    children: [
      { path: '', redirect: { name: 'discovery' } },
      {
        path: 'discovery',
        name: 'discovery',
        component: () => import('@/features/discovery/DiscoveryPage.vue'),
      },
      {
        path: 'square',
        name: 'square',
        component: () => import('@/features/square/SquarePage.vue'),
      },
      { path: 'chats', name: 'chats', component: () => import('@/features/chat/ChatsPage.vue') },
      { path: 'mine', name: 'mine', component: () => import('@/features/profile/MyProfilePage.vue') },
    ],
  },
  {
    path: '/chat/:peerId',
    name: 'chat',
    component: () => import('@/features/chat/ChatPage.vue'),
    props: true,
  },
  {
    path: '/users/:id',
    name: 'user-profile',
    component: () => import('@/features/profile/UserProfilePage.vue'),
    props: true,
  },
  {
    path: '/posts/compose',
    name: 'post-compose',
    component: () => import('@/features/square/PostComposePage.vue'),
  },
  {
    path: '/my-posts',
    name: 'my-posts',
    component: () => import('@/features/square/MyPostsPage.vue'),
  },
  {
    path: '/posts/:id',
    name: 'post-detail',
    component: () => import('@/features/square/PostDetailPage.vue'),
    props: true,
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/features/settings/SettingsPage.vue'),
  },
  {
    path: '/settings/blocks',
    name: 'settings-blocks',
    component: () => import('@/features/settings/BlockedUsersPage.vue'),
  },
  {
    path: '/profile/edit',
    name: 'profile-edit',
    component: () => import('@/features/profile/ProfileEditPage.vue'),
  },
  {
    path: '/preference',
    name: 'preference',
    component: () => import('@/features/profile/PreferencePage.vue'),
  },
]
