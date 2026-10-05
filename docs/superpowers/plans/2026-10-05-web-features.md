# 网页端实施计划(二):资料 / 发现配对 / 广场 / 设置(21 个任务)

> **For agentic workers:** REQUIRED SUB-SKILL: 用 `executing-plans` **内联**逐任务实现(项目全局约定:superpowers 类任务一律内联执行,不派发子 agent)。进度以本文件的 checkbox 为准。

**前置:** 计划一 `docs/superpowers/plans/2026-10-05-web-frontend.md` 的 T1–T3 必须已完成(工程骨架、心跳 token、8 个基础组件、`http`/`ApiError`/`tokenStore`/`sessionEvents`、`useSessionStore`、路由与守卫、`MobileGuard`、`useSidebar`/`layout`、`DesktopShell`、四个一级页空壳)。

**Goal:** 把「资料完善 → 发现滑卡 → 配对 → 广场动态 → 设置/拉黑/举报/在线状态」这五块从空壳变成真功能,全程对接真实 REST 接口。

**Architecture:** 每个领域一个 `api/*.ts`(纯请求)+ 一个 `stores/*.ts`(Pinia,持有状态与业务动作)+ `features/*` 下的页面组件。页面只碰 store,不直接调 `http`。

**Tech Stack:** 同计划一;本计划起使用 `Page<T>` 分页信封与 `PublicProfile` 等共享类型。

**接口契约来源(已核对真实文档,字段名不得臆造):** `docs/api/users.md`、`docs/api/discovery.md`、`docs/api/feed.md`、`docs/api/moderation.md`、`docs/api/conventions.md`。

## Global Constraints(与计划一相同,此处只列差异补充)

- 计划一的 Global Constraints **全部继续适用**(零改动红线、跨栈契约、token 双份纪律、禁止裸值、门禁、提交规范、非目标清单)。
- **分页信封**(conventions.md §分页):所有列表接口统一 `limit`/`offset`,响应形状固定为
  `{ "count": Integer, "next": String|null, "previous": String|null, "results": [] }`。
- **`id` 与 `user_id` 不是一回事**(users.md §2.1):`/users/me` 的 `id` 是**资料表主键**,跨接口引用用户一律用 `user_id`(账号 ID)。
- **封禁语义**:`status` 取值 `incomplete` / `complete` / `banned_light` / `banned_heavy`;`banned_light` 只禁滑卡(滑卡接口 403),`banned_heavy` 全域 403。
- 前端拦截(≤5MB、≤6 张、≤9 张)只是**体验优化**,后端仍会校验;错误文案以后端 `message` 为准,不自己编。

---

## 组 T4:引导与资料(6 个任务)

### Task 4.1:资料 API 与 store

**Files:**
- Create: `web/src/api/users.ts`、`web/src/stores/profile.ts`、`web/tests/support/pinia.ts`
- Modify: `web/src/api/types.ts`(追加本组类型)
- Test: `web/tests/unit/profile-store.spec.ts`

**测试基建(本任务起所有组件测试都用它)** —— 组件测试要「先预置 store 状态、再挂载组件」,而 `mount(..., { global: { plugins: [createPinia()] } })` 会新建一个**与预置状态无关的** pinia,组件读到的永远是空 store。统一改用:

`web/tests/support/pinia.ts`:

```ts
import { createPinia, setActivePinia, type Pinia } from 'pinia'

/**
 * 建一个 pinia 并设为 active,返回它本身 —— 测试里既用它预置 store 状态,
 * 又把它作为 `global.plugins: [pinia]` 传给 mount,保证组件与测试操作的是同一个 store。
 */
export function freshPinia(): Pinia {
  const pinia = createPinia()
  setActivePinia(pinia)
  return pinia
}
```

**Interfaces:**
- Consumes(计划一):`http`、`Page` 不需要、`parseApiError`。
- Produces(后续所有组都依赖,签名固定):

```ts
// —— 追加到 src/api/types.ts ——
export type Gender = 'male' | 'female'
export type ProfileStatus = 'incomplete' | 'complete' | 'banned_light' | 'banned_heavy'
export type PhotoStatus = 'pending' | 'approved' | 'rejected'

export interface Tag { id: number; name: string; icon: string }
export interface Photo { id: number; url: string; status: PhotoStatus; order: number }
export interface Preference {
  target_gender: Gender | null   // null = 不限
  age_min: number                // 默认 18
  age_max: number                // 默认 99
  city: string                   // 空字符串 = 不限
}
export interface Profile {
  id: number                     // 资料表主键(不是账号 ID)
  user_id: number                // 账号 ID
  phone: string
  nickname: string
  gender: Gender | ''
  birthday: string | null        // YYYY-MM-DD
  age: number | null
  city: string
  bio: string
  status: ProfileStatus
  ban_reason: string
  missing_fields: string[]       // nickname/gender/birthday/city/bio/photos
  tags: Tag[]
  photos: Photo[]
  preference: Preference
}
export interface PublicProfile {
  user_id: number; nickname: string; gender: Gender | ''; age: number | null
  city: string; bio: string; tags: Tag[]; photos: Photo[]
}
export interface Page<T> {
  count: number; next: string | null; previous: string | null; results: T[]
}
```

- `api/users.ts`:`fetchMe()`、`patchMe(patch)`、`fetchTags()`、`uploadPhoto(file)`、`deletePhoto(id)`、`fetchPreference()`、`patchPreference(patch)`、`fetchUserProfile(userId)`
- `useProfileStore()`:state `profile` / `tags` / `loading` / `error`;actions `load()`、`loadTags()`、`save(patch)`、`uploadPhoto(file)`、`removePhoto(id)`、`savePreference(patch)`
- 便捷判定:`isBannedHeavy`、`isBannedLight`、`isIncomplete`(computed)

- [ ] **Step 1:写失败的测试**

`web/tests/unit/profile-store.spec.ts`:

```ts
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { useProfileStore } from '@/stores/profile'
import { server } from '../support/server'

const mePayload = {
  id: 11,
  user_id: 9,
  phone: '13800000001',
  nickname: '',
  gender: '',
  birthday: null,
  age: null,
  city: '',
  bio: '',
  status: 'incomplete',
  ban_reason: '',
  missing_fields: ['nickname', 'photos'],
  tags: [],
  photos: [],
  preference: { target_gender: null, age_min: 18, age_max: 99, city: '' },
}

describe('profile store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('load 拉回资料并暴露缺项与封禁判定', async () => {
    server.use(mswHttp.get('/api/v1/users/me', () => HttpResponse.json(mePayload)))
    const store = useProfileStore()

    await store.load()

    expect(store.profile?.user_id).toBe(9)
    expect(store.isIncomplete).toBe(true)
    expect(store.isBannedHeavy).toBe(false)
    expect(store.missingFieldsText).toContain('昵称')
  })

  it('banned_heavy 时 isBannedHeavy 为真', async () => {
    server.use(
      mswHttp.get('/api/v1/users/me', () =>
        HttpResponse.json({ ...mePayload, status: 'banned_heavy', ban_reason: '违规' }),
      ),
    )
    const store = useProfileStore()
    await store.load()
    expect(store.isBannedHeavy).toBe(true)
    expect(store.profile?.ban_reason).toBe('违规')
  })

  it('save 后资料被替换为服务端返回的最新值', async () => {
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(mePayload)),
      mswHttp.patch('/api/v1/users/me', () =>
        HttpResponse.json({ ...mePayload, nickname: '小雨', status: 'incomplete', missing_fields: ['photos'] }),
      ),
    )
    const store = useProfileStore()
    await store.load()

    await store.save({ nickname: '小雨' })

    expect(store.profile?.nickname).toBe('小雨')
    expect(store.profile?.missing_fields).toEqual(['photos'])
  })

  it('上传照片走 multipart,字段名固定为 file', async () => {
    let receivedName: string | null = null
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(mePayload)),
      mswHttp.post('/api/v1/users/me/photos', async ({ request }) => {
        const form = await request.formData()
        receivedName = (form.get('file') as File | null)?.name ?? null
        return HttpResponse.json({ id: 3, url: 'https://cdn/x.jpg', status: 'pending', order: 0 })
      }),
    )
    const store = useProfileStore()
    await store.load()

    await store.uploadPhoto(new File(['x'], 'me.jpg', { type: 'image/jpeg' }))

    expect(receivedName).toBe('me.jpg')
    expect(store.profile?.photos).toHaveLength(1)
  })

  it('加载失败时记录错误文案', async () => {
    server.use(
      mswHttp.get('/api/v1/users/me', () =>
        HttpResponse.json({ code: 50002, message: '服务器开小差了', request_id: 'r' }, { status: 500 }),
      ),
    )
    const store = useProfileStore()
    await store.load()
    expect(store.error).toBe('服务器开小差了')
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/unit/profile-store.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现 `api/users.ts`**

```ts
import { http } from './http'
import type { Page, Photo, Preference, Profile, PublicProfile, Tag } from './types'

export async function fetchMe(): Promise<Profile> {
  const { data } = await http.get('/users/me')
  return data as Profile
}

/** 只需传要改的字段;tag_ids 是全量替换。 */
export async function patchMe(patch: Record<string, unknown>): Promise<Profile> {
  const { data } = await http.patch('/users/me', patch)
  return data as Profile
}

export async function fetchTags(): Promise<Tag[]> {
  const { data } = await http.get('/users/tags')
  return data as Tag[]
}

export async function uploadPhoto(file: File): Promise<Photo> {
  const form = new FormData()
  form.append('file', file) // 字段名固定为 file(users.md §2.4)
  const { data } = await http.post('/users/me/photos', form)
  return data as Photo
}

export async function deletePhoto(photoId: number): Promise<void> {
  await http.delete(`/users/me/photos/${photoId}`)
}

export async function fetchPreference(): Promise<Preference> {
  const { data } = await http.get('/users/me/preference')
  return data as Preference
}

export async function patchPreference(patch: Partial<Preference>): Promise<Preference> {
  const { data } = await http.patch('/users/me/preference', patch)
  return data as Preference
}

export async function fetchUserProfile(userId: number): Promise<PublicProfile> {
  const { data } = await http.get(`/users/${userId}`)
  return data as PublicProfile
}

export type { Page }
```

- [ ] **Step 4:实现 `stores/profile.ts`**

```ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as usersApi from '@/api/users'
import { parseApiError } from '@/api/error'
import type { Preference, Profile, Tag } from '@/api/types'

/** 缺项英文键 → 中文提示(顺序与后端 missing_fields 的返回顺序无关)。 */
const MISSING_LABELS: Record<string, string> = {
  nickname: '昵称',
  gender: '性别',
  birthday: '生日',
  city: '城市',
  bio: '简介',
  photos: '照片',
}

export const useProfileStore = defineStore('profile', () => {
  const profile = ref<Profile | null>(null)
  const tags = ref<Tag[]>([])
  const loading = ref(false)
  const error = ref('')

  const isBannedHeavy = computed(() => profile.value?.status === 'banned_heavy')
  const isBannedLight = computed(() => profile.value?.status === 'banned_light')
  const isIncomplete = computed(() => profile.value?.status === 'incomplete')
  const missingFieldsText = computed(() =>
    (profile.value?.missing_fields ?? []).map((f) => MISSING_LABELS[f] ?? f).join('、'),
  )

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      profile.value = await usersApi.fetchMe()
    } catch (e) {
      error.value = parseApiError(e).message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function loadTags(): Promise<void> {
    if (tags.value.length > 0) return // 标签池是静态数据,拉一次即可
    tags.value = await usersApi.fetchTags()
  }

  async function save(patch: Record<string, unknown>): Promise<void> {
    profile.value = await usersApi.patchMe(patch)
  }

  async function uploadPhoto(file: File): Promise<void> {
    const photo = await usersApi.uploadPhoto(file)
    if (profile.value) profile.value.photos = [...profile.value.photos, photo]
  }

  async function removePhoto(photoId: number): Promise<void> {
    await usersApi.deletePhoto(photoId)
    if (profile.value) profile.value.photos = profile.value.photos.filter((p) => p.id !== photoId)
  }

  async function savePreference(patch: Partial<Preference>): Promise<void> {
    const preference = await usersApi.patchPreference(patch)
    if (profile.value) profile.value.preference = preference
  }

  return {
    profile, tags, loading, error,
    isBannedHeavy, isBannedLight, isIncomplete, missingFieldsText,
    load, loadTags, save, uploadPhoto, removePhoto, savePreference,
  }
})
```

- [ ] **Step 5:跑测试确认通过** → Run: `cd web && npm run test:run tests/unit/profile-store.spec.ts && npm run type-check`
Expected: 5 passed

- [ ] **Step 6:提交**

```bash
git add web/src/api web/src/stores web/tests/unit
git commit -m "feat(web): 资料 API 与 store(含缺项提示与封禁判定)"
```

### Task 4.2:编辑资料页

**Files:**
- Create: `web/src/features/profile/ProfileEditPage.vue`
- Test: `web/tests/component/profile-edit-page.spec.ts`

**Interfaces:**
- Consumes: `useProfileStore()`、`FormCard`、`AppInput`、`AppButton`。
- Produces:`ProfileEditPage`(路由 `/profile/edit`),提交昵称/性别/生日/城市/简介;**未满 18 岁由后端 400 拒绝,前端展示后端文案**。

- [ ] **Step 1:写失败的测试**

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import ProfileEditPage from '@/features/profile/ProfileEditPage.vue'
import { useProfileStore } from '@/stores/profile'
import { freshPinia } from '../support/pinia'
import { server } from '../support/server'

const me = {
  id: 11, user_id: 9, phone: '13800000001', nickname: '小雨', gender: 'female',
  birthday: '2000-01-01', age: 26, city: '上海', bio: '你好', status: 'complete',
  ban_reason: '', missing_fields: [], tags: [], photos: [],
  preference: { target_gender: null, age_min: 18, age_max: 99, city: '' },
}

async function mountPage() {
  server.use(mswHttp.get('/api/v1/users/me', () => HttpResponse.json(me)))
  const pinia = freshPinia() // 预置状态的 pinia 必须与挂载时用的是同一个
  const store = useProfileStore()
  await store.load()
  const w = mount(ProfileEditPage, {
    global: { plugins: [pinia], stubs: { RouterLink: true } },
  })
  await flushPromises()
  return w
}

describe('ProfileEditPage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('用现有资料预填表单', async () => {
    const w = await mountPage()
    expect((w.find('input[type="text"]').element as HTMLInputElement).value).toBe('小雨')
  })

  it('提交后调用 PATCH 并展示成功反馈', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(me)),
      mswHttp.patch('/api/v1/users/me', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...me, nickname: '阿泽' })
      }),
    )
    const pinia = freshPinia()
    const store = useProfileStore()
    await store.load()
    const w = mount(ProfileEditPage, { global: { plugins: [pinia], stubs: { RouterLink: true } } })
    await flushPromises()

    await w.find('input[type="text"]').setValue('阿泽')
    await w.find('.profile-edit__submit').trigger('click')
    await flushPromises()

    expect(body).toMatchObject({ nickname: '阿泽' })
    expect(w.text()).toContain('已保存')
  })

  it('未满 18 岁时展示后端文案', async () => {
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(me)),
      mswHttp.patch('/api/v1/users/me', () =>
        HttpResponse.json({ code: 40001, message: '未满 18 周岁不能使用本服务', request_id: 'r' }, { status: 400 }),
      ),
    )
    const pinia = freshPinia()
    const store = useProfileStore()
    await store.load()
    const w = mount(ProfileEditPage, { global: { plugins: [pinia], stubs: { RouterLink: true } } })
    await flushPromises()

    await w.find('.profile-edit__submit').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('未满 18 周岁不能使用本服务')
  })
})
```

> 注意:每个用例都新建了 Pinia,但 `store.load()` 在 `server.use` 之后调用 —— 顺序不能反,否则会打到上一个用例的 handler。

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/component/profile-edit-page.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现**

```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { parseApiError } from '@/api/error'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import FormCard from '@/features/auth/FormCard.vue'
import { useProfileStore } from '@/stores/profile'

const store = useProfileStore()

const nickname = ref('')
const gender = ref<'' | 'male' | 'female'>('')
const birthday = ref('')
const city = ref('')
const bio = ref('')
const error = ref('')
const saved = ref(false)
const submitting = ref(false)

onMounted(async () => {
  if (!store.profile) await store.load().catch(() => {})
  nickname.value = store.profile?.nickname ?? ''
  gender.value = store.profile?.gender ?? ''
  birthday.value = store.profile?.birthday ?? ''
  city.value = store.profile?.city ?? ''
  bio.value = store.profile?.bio ?? ''
})

async function onSubmit() {
  error.value = ''
  saved.value = false
  submitting.value = true
  try {
    await store.save({
      nickname: nickname.value,
      gender: gender.value || undefined,
      birthday: birthday.value || undefined,
      city: city.value,
      bio: bio.value,
    })
    saved.value = true
  } catch (e) {
    error.value = parseApiError(e).message
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <FormCard title="编辑资料" description="资料越完整,越容易被喜欢">
    <div class="profile-edit__form">
      <AppInput v-model="nickname" placeholder="昵称(最多 20 字)" :maxlength="20" :error="error" />
      <div class="profile-edit__gender">
        <button
          v-for="option in [{ v: 'female', label: '女生' }, { v: 'male', label: '男生' }]"
          :key="option.v"
          type="button"
          class="profile-edit__chip"
          :class="{ 'profile-edit__chip--active': gender === option.v }"
          @click="gender = option.v as 'male' | 'female'"
        >
          {{ option.label }}
        </button>
      </div>
      <AppInput v-model="birthday" type="date" placeholder="生日" />
      <AppInput v-model="city" placeholder="城市" :maxlength="50" />
      <AppInput v-model="bio" placeholder="一句话介绍自己(最多 200 字)" :maxlength="200" />
    </div>
    <p v-if="saved" class="profile-edit__saved">已保存</p>
    <AppButton class="profile-edit__submit" block size="lg" :loading="submitting" @click="onSubmit">
      保存
    </AppButton>
  </FormCard>
</template>

<style scoped>
.profile-edit__form { display: flex; flex-direction: column; gap: var(--space-md); }
.profile-edit__gender { display: flex; gap: var(--space-sm); }
.profile-edit__chip {
  flex: 1;
  height: 44px;
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-input);
  background: var(--color-bg-card);
  cursor: pointer;
  transition: border-color var(--motion-fast) var(--ease-out), color var(--motion-fast) var(--ease-out);
}
.profile-edit__chip--active { border-color: var(--color-brand); color: var(--color-brand); }
.profile-edit__saved { margin: 0; font-size: var(--text-caption); color: var(--color-green); }
</style>
```

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 5:提交**

```bash
git add web/src/features/profile web/tests/component
git commit -m "feat(web): 编辑资料页"
```

### Task 4.3:标签选择

**Files:**
- Create: `web/src/features/profile/TagPicker.vue`
- Modify: `web/src/features/profile/ProfileEditPage.vue`(接入)
- Test: `web/tests/component/tag-picker.spec.ts`

**Interfaces:**
- Consumes: `useProfileStore().tags` / `loadTags()`、`save({ tag_ids })`。
- Produces:`TagPicker.vue` —— props `{ modelValue: number[] }`,emits `update:modelValue`;多选,选中态用 brand 描边;提交时 `tag_ids` **全量替换**(users.md §2.2)。

- [ ] **Step 1:写失败的测试**

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import TagPicker from '@/features/profile/TagPicker.vue'
import { useProfileStore } from '@/stores/profile'
import { server } from '../support/server'

const tags = [
  { id: 1, name: '旅行', icon: 'plane' },
  { id: 2, name: '电影', icon: 'film' },
]

describe('TagPicker', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('渲染标签池并展示已选项', async () => {
    server.use(mswHttp.get('/api/v1/users/tags', () => HttpResponse.json(tags)))
    const store = useProfileStore()
    await store.loadTags()
    const w = mount(TagPicker, {
      props: { modelValue: [2] },
      global: { plugins: [createPinia()] },
    })
    await flushPromises()

    expect(w.findAll('.tag-picker__chip')).toHaveLength(2)
    expect(w.findAll('.tag-picker__chip')[1].classes()).toContain('tag-picker__chip--active')
  })

  it('点击未选项 → 追加到 modelValue', async () => {
    server.use(mswHttp.get('/api/v1/users/tags', () => HttpResponse.json(tags)))
    const store = useProfileStore()
    await store.loadTags()
    const w = mount(TagPicker, { props: { modelValue: [] }, global: { plugins: [createPinia()] } })
    await flushPromises()

    await w.findAll('.tag-picker__chip')[0].trigger('click')

    expect(w.emitted('update:modelValue')?.[0]).toEqual([[1]])
  })

  it('点击已选项 → 从 modelValue 移除', async () => {
    server.use(mswHttp.get('/api/v1/users/tags', () => HttpResponse.json(tags)))
    const store = useProfileStore()
    await store.loadTags()
    const w = mount(TagPicker, { props: { modelValue: [1, 2] }, global: { plugins: [createPinia()] } })
    await flushPromises()

    await w.findAll('.tag-picker__chip')[0].trigger('click')

    expect(w.emitted('update:modelValue')?.[0]).toEqual([[2]])
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/component/tag-picker.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现 `TagPicker.vue`**

```vue
<script setup lang="ts">
import { onMounted } from 'vue'
import { useProfileStore } from '@/stores/profile'

const props = defineProps<{ modelValue: number[] }>()
const emit = defineEmits<{ 'update:modelValue': [number[]] }>()

const store = useProfileStore()

onMounted(() => {
  store.loadTags().catch(() => {})
})

function toggle(id: number) {
  const next = props.modelValue.includes(id)
    ? props.modelValue.filter((x) => x !== id)
    : [...props.modelValue, id]
  emit('update:modelValue', next)
}
</script>

<template>
  <div class="tag-picker">
    <button
      v-for="tag in store.tags"
      :key="tag.id"
      type="button"
      class="tag-picker__chip"
      :class="{ 'tag-picker__chip--active': props.modelValue.includes(tag.id) }"
      @click="toggle(tag.id)"
    >
      {{ tag.name }}
    </button>
  </div>
</template>

<style scoped>
.tag-picker { display: flex; flex-wrap: wrap; gap: var(--space-sm); }
.tag-picker__chip {
  height: 32px;
  padding: 0 var(--space-md);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  font-size: var(--text-caption);
  cursor: pointer;
  transition: border-color var(--motion-fast) var(--ease-out), color var(--motion-fast) var(--ease-out);
}
.tag-picker__chip:hover { background: var(--hover-overlay); }
.tag-picker__chip--active { border-color: var(--color-brand); color: var(--color-brand); }
</style>
```

- [ ] **Step 4:接进编辑页**

`ProfileEditPage.vue` 里:引入 `TagPicker`,加 `const tagIds = ref<number[]>([])`,`onMounted` 里 `tagIds.value = store.profile?.tags.map(t => t.id) ?? []`,模板中放在简介下方,提交时带上 `tag_ids: tagIds.value`(空数组表示清空,**不要**用 `undefined`,否则后端不替换)。

- [ ] **Step 5:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 6:提交**

```bash
git add web/src/features/profile web/tests/component
git commit -m "feat(web): 标签选择(全量替换 tag_ids)"
```

### Task 4.4:照片网格(上传 / 删除 / 审核状态)

**Files:**
- Create: `web/src/features/profile/PhotoGrid.vue`
- Modify: `web/src/features/profile/ProfileEditPage.vue`(接入)、`web/src/features/profile/MyProfilePage.vue`(只读展示)
- Test: `web/tests/component/photo-grid.spec.ts`

**Interfaces:**
- Consumes: `useProfileStore().profile.photos` / `uploadPhoto(file)` / `removePhoto(id)`。
- Produces:`PhotoGrid.vue` —— props `{ editable?: boolean }`(默认 true);前端拦截:单张 ≤5MB、最多 6 张(users.md §2.4 的 400 文案是兜底);每张显示审核徽标(`pending` 黄 / `approved` 绿 / `rejected` 红)。

- [ ] **Step 1:写失败的测试**

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import PhotoGrid from '@/features/profile/PhotoGrid.vue'
import { useProfileStore } from '@/stores/profile'
import { server } from '../support/server'

function profileWithPhotos(count: number) {
  return {
    id: 11, user_id: 9, phone: '13800000001', nickname: '小雨', gender: 'female',
    birthday: '2000-01-01', age: 26, city: '上海', bio: '', status: 'complete',
    ban_reason: '', missing_fields: [], tags: [],
    photos: Array.from({ length: count }, (_, i) => ({
      id: i + 1, url: `https://cdn/${i}.jpg`, status: 'approved', order: i,
    })),
    preference: { target_gender: null, age_min: 18, age_max: 99, city: '' },
  }
}

async function mountGrid(count: number) {
  server.use(mswHttp.get('/api/v1/users/me', () => HttpResponse.json(profileWithPhotos(count))))
  const store = useProfileStore()
  await store.load()
  const w = mount(PhotoGrid, { global: { plugins: [createPinia()] } })
  await flushPromises()
  return { w, store }
}

describe('PhotoGrid', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('渲染已有照片与审核徽标', async () => {
    const { w } = await mountGrid(2)
    expect(w.findAll('.photo-grid__item')).toHaveLength(2)
    expect(w.findAll('.photo-grid__badge')[0].text()).toBe('已通过')
  })

  it('超过 5MB 的文件被前端拦下并给提示', async () => {
    const { w } = await mountGrid(0)
    const big = new File([new Uint8Array(6 * 1024 * 1024)], 'big.jpg', { type: 'image/jpeg' })
    const input = w.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [big] })
    await input.trigger('change')
    await flushPromises()

    expect(w.text()).toContain('单张照片不能超过 5MB')
  })

  it('已有 6 张时不再允许上传', async () => {
    const { w } = await mountGrid(6)
    expect(w.find('input[type="file"]').exists()).toBe(false)
    expect(w.text()).toContain('最多 6 张')
  })

  it('删除调用后端并从网格移除', async () => {
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(profileWithPhotos(2))),
      mswHttp.delete('/api/v1/users/me/photos/1', () => new HttpResponse(null, { status: 204 })),
    )
    const store = useProfileStore()
    await store.load()
    const w = mount(PhotoGrid, { global: { plugins: [createPinia()] } })
    await flushPromises()

    await w.findAll('.photo-grid__remove')[0].trigger('click')
    await flushPromises()

    expect(store.profile?.photos).toHaveLength(1)
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/component/photo-grid.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现**

```vue
<script setup lang="ts">
import { computed, ref } from 'vue'
import { parseApiError } from '@/api/error'
import { useProfileStore } from '@/stores/profile'

const props = withDefaults(defineProps<{ editable?: boolean }>(), { editable: true })

const MAX_COUNT = 6
const MAX_BYTES = 5 * 1024 * 1024

const STATUS_LABEL: Record<string, string> = {
  pending: '审核中',
  approved: '已通过',
  rejected: '已驳回',
}

const store = useProfileStore()
const hint = ref('')
const busy = ref(false)

const photos = computed(() => store.profile?.photos ?? [])
const canUpload = computed(() => props.editable && photos.value.length < MAX_COUNT)

async function onPick(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // 允许重复选择同一文件
  if (!file) return

  hint.value = ''
  if (file.size > MAX_BYTES) {
    hint.value = '单张照片不能超过 5MB'
    return
  }
  busy.value = true
  try {
    await store.uploadPhoto(file)
  } catch (e) {
    hint.value = parseApiError(e).message
  } finally {
    busy.value = false
  }
}

async function onRemove(id: number) {
  hint.value = ''
  try {
    await store.removePhoto(id)
  } catch (e) {
    hint.value = parseApiError(e).message
  }
}
</script>

<template>
  <div class="photo-grid">
    <figure v-for="photo in photos" :key="photo.id" class="photo-grid__item">
      <img :src="photo.url" alt="" class="photo-grid__img" />
      <figcaption class="photo-grid__badge" :class="`photo-grid__badge--${photo.status}`">
        {{ STATUS_LABEL[photo.status] }}
      </figcaption>
      <button
        v-if="props.editable"
        type="button"
        class="photo-grid__remove"
        aria-label="删除照片"
        @click="onRemove(photo.id)"
      >
        ×
      </button>
    </figure>

    <label v-if="canUpload" class="photo-grid__add">
      <input type="file" accept="image/*" class="photo-grid__input" @change="onPick" />
      <span>{{ busy ? '上传中…' : '+' }}</span>
    </label>

    <p v-if="props.editable && !canUpload" class="photo-grid__hint">最多 6 张</p>
    <p v-if="hint" class="photo-grid__hint photo-grid__hint--error">{{ hint }}</p>
  </div>
</template>

<style scoped>
.photo-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-md);
}
.photo-grid__item {
  position: relative;
  margin: 0;
  aspect-ratio: 3 / 4;
  border-radius: var(--radius-image);
  overflow: hidden;
  background: var(--color-divider);
}
.photo-grid__img { width: 100%; height: 100%; object-fit: cover; }
.photo-grid__badge {
  position: absolute;
  left: var(--space-xs);
  bottom: var(--space-xs);
  padding: 2px var(--space-sm);
  border-radius: var(--radius-full);
  font-size: var(--text-badge);
  color: var(--color-bg-card);
  background: var(--color-text2);
}
.photo-grid__badge--approved { background: var(--color-green); }
.photo-grid__badge--rejected { background: var(--color-danger); }
.photo-grid__badge--pending { background: var(--color-amber); }
.photo-grid__remove {
  position: absolute;
  top: var(--space-xs);
  right: var(--space-xs);
  width: 24px;
  height: 24px;
  border: none;
  border-radius: var(--radius-full);
  background: var(--color-photo-scrim);
  color: var(--color-bg-card);
  cursor: pointer;
}
.photo-grid__add {
  display: flex;
  align-items: center;
  justify-content: center;
  aspect-ratio: 3 / 4;
  border: 1px dashed var(--color-text3);
  border-radius: var(--radius-image);
  color: var(--color-text3);
  font-size: var(--text-display);
  cursor: pointer;
}
.photo-grid__input { display: none; }
.photo-grid__hint { grid-column: 1 / -1; margin: 0; font-size: var(--text-caption); color: var(--color-text2); }
.photo-grid__hint--error { color: var(--color-danger); }
</style>
```

> 后端 `400` 文案(「最多上传 6 张照片」「图片不能超过 5MB」)是最终兜底:前端拦截只是省一次往返,`catch` 里仍要展示后端 `message`。

- [ ] **Step 4:接入我的页与编辑页**

- `ProfileEditPage.vue`:简介下方加 `<PhotoGrid />`(可编辑)
- `MyProfilePage.vue`(Task 4.6 实现)里用 `<PhotoGrid :editable="false" />`

- [ ] **Step 5:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 6:提交**

```bash
git add web/src/features/profile web/tests/component
git commit -m "feat(web): 照片网格(上传/删除/审核状态/前端拦截)"
```

### Task 4.5:择偶偏好页

**Files:**
- Create: `web/src/features/profile/PreferencePage.vue`
- Test: `web/tests/component/preference-page.spec.ts`

**Interfaces:**
- Consumes: `useProfileStore().profile.preference` / `savePreference(patch)`。
- Produces:`PreferencePage`(路由 `/preference`);目标性别三选(**不限 = `null`**)、年龄区间(最小不能小于 18)、城市(空 = 不限);错误文案用后端返回。

- [ ] **Step 1:写失败的测试**

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import PreferencePage from '@/features/profile/PreferencePage.vue'
import { useProfileStore } from '@/stores/profile'
import { freshPinia } from '../support/pinia'
import { server } from '../support/server'

const me = {
  id: 11, user_id: 9, phone: '13800000001', nickname: '小雨', gender: 'female',
  birthday: '2000-01-01', age: 26, city: '上海', bio: '', status: 'complete',
  ban_reason: '', missing_fields: [], tags: [], photos: [],
  preference: { target_gender: null, age_min: 18, age_max: 99, city: '' },
}

async function mountPage() {
  server.use(mswHttp.get('/api/v1/users/me', () => HttpResponse.json(me)))
  const pinia = freshPinia()
  const store = useProfileStore()
  await store.load()
  const w = mount(PreferencePage, { global: { plugins: [pinia], stubs: { RouterLink: true } } })
  await flushPromises()
  return w
}

describe('PreferencePage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('不限性别用 null 提交', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(me)),
      mswHttp.patch('/api/v1/users/me/preference', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(me.preference)
      }),
    )
    const pinia = freshPinia()
    const store = useProfileStore()
    await store.load()
    const w = mount(PreferencePage, { global: { plugins: [pinia], stubs: { RouterLink: true } } })
    await flushPromises()

    await w.find('.preference__gender button').trigger('click') // 第一个是「不限」
    await w.find('.preference__submit').trigger('click')
    await flushPromises()

    expect(body).toMatchObject({ target_gender: null })
  })

  it('后端拒绝时展示后端文案', async () => {
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(me)),
      mswHttp.patch('/api/v1/users/me/preference', () =>
        HttpResponse.json({ code: 40002, message: '最小年龄不能小于 18', request_id: 'r' }, { status: 400 }),
      ),
    )
    const pinia = freshPinia()
    const store = useProfileStore()
    await store.load()
    const w = mount(PreferencePage, { global: { plugins: [pinia], stubs: { RouterLink: true } } })
    await flushPromises()

    await w.find('.preference__submit').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('最小年龄不能小于 18')
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/component/preference-page.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现**

```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { parseApiError } from '@/api/error'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import FormCard from '@/features/auth/FormCard.vue'
import { useProfileStore } from '@/stores/profile'
import type { Gender } from '@/api/types'

const store = useProfileStore()

const targetGender = ref<Gender | null>(null)
const ageMin = ref(18)
const ageMax = ref(99)
const city = ref('')
const error = ref('')
const saved = ref(false)

onMounted(async () => {
  if (!store.profile) await store.load().catch(() => {})
  const pref = store.profile?.preference
  if (!pref) return
  targetGender.value = pref.target_gender
  ageMin.value = pref.age_min
  ageMax.value = pref.age_max
  city.value = pref.city
})

async function onSubmit() {
  error.value = ''
  saved.value = false
  try {
    await store.savePreference({
      target_gender: targetGender.value, // null = 不限(users.md §2.7)
      age_min: Number(ageMin.value),
      age_max: Number(ageMax.value),
      city: city.value,
    })
    saved.value = true
  } catch (e) {
    error.value = parseApiError(e).message
  }
}
</script>

<template>
  <FormCard title="想找的人" description="偏好只影响推荐,随时可以改">
    <div class="preference__gender">
      <button
        v-for="option in [
          { v: null, label: '不限' },
          { v: 'female', label: '女生' },
          { v: 'male', label: '男生' },
        ]"
        :key="String(option.v)"
        type="button"
        class="preference__chip"
        :class="{ 'preference__chip--active': targetGender === option.v }"
        @click="targetGender = option.v as Gender | null"
      >
        {{ option.label }}
      </button>
    </div>

    <div class="preference__ages">
      <AppInput
        :model-value="String(ageMin)"
        type="number"
        placeholder="最小年龄"
        @update:model-value="ageMin = Number($event)"
      />
      <span class="preference__dash">—</span>
      <AppInput
        :model-value="String(ageMax)"
        type="number"
        placeholder="最大年龄"
        @update:model-value="ageMax = Number($event)"
      />
    </div>

    <AppInput v-model="city" placeholder="想找的城市(留空=不限)" :maxlength="50" />
    <p v-if="error" class="preference__error">{{ error }}</p>
    <p v-if="saved" class="preference__saved">已保存</p>
    <AppButton class="preference__submit" block size="lg" @click="onSubmit">保存</AppButton>
  </FormCard>
</template>

<style scoped>
.preference__gender { display: flex; gap: var(--space-sm); }
.preference__chip {
  flex: 1;
  height: 44px;
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-input);
  background: var(--color-bg-card);
  cursor: pointer;
}
.preference__chip--active { border-color: var(--color-brand); color: var(--color-brand); }
.preference__ages { display: flex; align-items: center; gap: var(--space-sm); }
.preference__dash { color: var(--color-text3); }
.preference__error { margin: 0; font-size: var(--text-caption); color: var(--color-danger); }
.preference__saved { margin: 0; font-size: var(--text-caption); color: var(--color-green); }
</style>
```

> `FormCard` 的插槽里有多个根节点,注意 `FormCard` 内部用的是默认插槽(计划一 Task 2.5 已定义),多个子节点是允许的。

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 5:提交**

```bash
git add web/src/features/profile web/tests/component
git commit -m "feat(web): 择偶偏好页(不限性别用 null)"
```

### Task 4.6:我的页、完善资料页与封禁守卫

**Files:**
- Create: `web/src/features/profile/MyProfilePage.vue`、`web/src/features/onboarding/OnboardingPage.vue`(替换空壳)
- Modify: `web/src/router/index.ts`(加封禁守卫)
- Test: `web/tests/unit/banned-guard.spec.ts`、`web/tests/component/my-profile-page.spec.ts`

**Interfaces:**
- Consumes: `useProfileStore()`、`PhotoGrid`、`AppCard`、`AppAvatar`。
- Produces:
  - `MyProfilePage`(路由 `/home/mine`):资料卡 + 完善度提示条(点进 `/onboarding`)+ 照片 + 偏好入口 + 设置入口
  - `OnboardingPage`(路由 `/onboarding`):复用编辑资料 + 标签 + 照片;完善后跳 `/home/discovery`
  - 守卫:**`banned_heavy` → `/banned`**(spec §5.1)

- [ ] **Step 1:写失败的封禁守卫测试**

`web/tests/unit/banned-guard.spec.ts`:

```ts
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createAppRouter } from '@/router'
import { tokenStore } from '@/api/token-store'
import { server } from '../support/server'

vi.mock('@/composables/useDevice', () => ({ isMobileDevice: () => false }))

const bannedHeavy = {
  id: 11, user_id: 9, phone: '13800000001', nickname: '小雨', gender: 'female',
  birthday: '2000-01-01', age: 26, city: '上海', bio: '', status: 'banned_heavy',
  ban_reason: '发布违规内容', missing_fields: [], tags: [], photos: [],
  preference: { target_gender: null, age_min: 18, age_max: 99, city: '' },
}

describe('封禁守卫', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    localStorage.setItem('hb.legalAgreed', '1')
    tokenStore.access = 'a'
    tokenStore.refresh = 'r'
  })

  it('banned_heavy 用户被送到 /banned', async () => {
    server.use(mswHttp.get('/api/v1/users/me', () => HttpResponse.json(bannedHeavy)))
    const router = createAppRouter()
    await router.push('/home/discovery')
    expect(router.currentRoute.value.path).toBe('/banned')
  })

  it('正常用户留在发现页', async () => {
    server.use(
      mswHttp.get('/api/v1/users/me', () =>
        HttpResponse.json({ ...bannedHeavy, status: 'complete', ban_reason: '' }),
      ),
    )
    const router = createAppRouter()
    await router.push('/home/discovery')
    expect(router.currentRoute.value.path).toBe('/home/discovery')
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/unit/banned-guard.spec.ts`;Expected: FAIL(当前守卫不检查封禁)

- [ ] **Step 3:在守卫里补封禁分支**

`web/src/router/index.ts` 的 `beforeEach` 中,在「非公开路由」判定之后追加:

```ts
    // 4) 封禁:重封禁全域拦截(spec §5.1)。
    //    资料只在首次进入时拉一次,避免每次路由跳转都打接口。
    const profile = useProfileStore()
    if (!profile.profile) {
      await profile.load().catch(() => {})
    }
    if (profile.isBannedHeavy && to.name !== 'banned') {
      return { name: 'banned' }
    }
```

同步在文件顶部 `import { useProfileStore } from '@/stores/profile'`;`/banned` 路由已带 `meta.public`(计划一 Task 3.1),故不会被「未登录」分支拦掉。

- [ ] **Step 4:写「我的页」测试**

`web/tests/component/my-profile-page.spec.ts`:

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import MyProfilePage from '@/features/profile/MyProfilePage.vue'
import { useProfileStore } from '@/stores/profile'
import { freshPinia } from '../support/pinia'
import { server } from '../support/server'

const incomplete = {
  id: 11, user_id: 9, phone: '13800000001', nickname: '小雨', gender: 'female',
  birthday: '2000-01-01', age: 26, city: '上海', bio: '你好', status: 'incomplete',
  ban_reason: '', missing_fields: ['photos'], tags: [{ id: 1, name: '旅行', icon: 'plane' }],
  photos: [], preference: { target_gender: null, age_min: 18, age_max: 99, city: '' },
}

describe('MyProfilePage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('资料不完整时展示缺项与完善入口', async () => {
    server.use(mswHttp.get('/api/v1/users/me', () => HttpResponse.json(incomplete)))
    const pinia = freshPinia()
    const store = useProfileStore()
    await store.load()
    const w = mount(MyProfilePage, {
      global: { plugins: [pinia], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    expect(w.text()).toContain('还差:照片')
    expect(w.find('.my-profile__complete').exists()).toBe(true)
  })

  it('资料完整时不展示完善入口', async () => {
    server.use(
      mswHttp.get('/api/v1/users/me', () =>
        HttpResponse.json({ ...incomplete, status: 'complete', missing_fields: [] }),
      ),
    )
    const pinia = freshPinia()
    const store = useProfileStore()
    await store.load()
    const w = mount(MyProfilePage, {
      global: { plugins: [pinia], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    expect(w.find('.my-profile__complete').exists()).toBe(false)
  })
})
```

- [ ] **Step 5:实现 `MyProfilePage.vue`**

```vue
<script setup lang="ts">
import { onMounted } from 'vue'
import AppAvatar from '@/components/AppAvatar.vue'
import AppButton from '@/components/AppButton.vue'
import AppCard from '@/components/AppCard.vue'
import PhotoGrid from './PhotoGrid.vue'
import { useProfileStore } from '@/stores/profile'

const store = useProfileStore()

onMounted(() => {
  if (!store.profile) store.load().catch(() => {})
})
</script>

<template>
  <section class="my-profile">
    <AppCard padding="lg">
      <div class="my-profile__head">
        <AppAvatar :src="store.profile?.photos[0]?.url ?? null" :name="store.profile?.nickname" :size="64" />
        <div class="my-profile__meta">
          <h1 class="my-profile__name">{{ store.profile?.nickname || '未设置昵称' }}</h1>
          <p class="my-profile__sub">
            {{ store.profile?.age ?? '—' }} 岁 · {{ store.profile?.city || '未填城市' }}
          </p>
        </div>
      </div>
      <p v-if="store.profile?.bio" class="my-profile__bio">{{ store.profile.bio }}</p>

      <div v-if="store.isIncomplete" class="my-profile__complete">
        <span>还差:{{ store.missingFieldsText }}</span>
        <RouterLink :to="{ name: 'onboarding' }">
          <AppButton size="md">去完善</AppButton>
        </RouterLink>
      </div>
    </AppCard>

    <AppCard padding="lg">
      <h2 class="my-profile__section">我的照片</h2>
      <PhotoGrid :editable="false" />
    </AppCard>

    <div class="my-profile__links">
      <RouterLink :to="{ name: 'profile-edit' }"><AppButton variant="ghost" block>编辑资料</AppButton></RouterLink>
      <RouterLink :to="{ name: 'preference' }"><AppButton variant="ghost" block>想找的人</AppButton></RouterLink>
      <RouterLink :to="{ name: 'settings' }"><AppButton variant="ghost" block>设置</AppButton></RouterLink>
    </div>
  </section>
</template>

<style scoped>
.my-profile {
  display: flex;
  flex-direction: column;
  gap: var(--space-card-gap);
  max-width: clamp(560px, 56%, 760px);
  margin: 0 auto;
  padding: var(--space-section-gap) var(--space-page-h);
}
.my-profile__head { display: flex; align-items: center; gap: var(--space-lg); }
.my-profile__meta { display: flex; flex-direction: column; gap: var(--space-xs); }
.my-profile__name { margin: 0; font-size: var(--text-title); font-weight: var(--weight-bold); }
.my-profile__sub { margin: 0; font-size: var(--text-caption); color: var(--color-text2); }
.my-profile__bio { margin: var(--space-md) 0 0; font-size: var(--text-body); }
.my-profile__complete {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
  margin-top: var(--space-lg);
  padding: var(--space-md);
  border-radius: var(--radius-chip);
  background: rgb(255 44 85 / 8%);
  color: var(--color-brand);
  font-size: var(--text-caption);
}
.my-profile__section { margin: 0 0 var(--space-md); font-size: var(--text-subtitle); font-weight: var(--weight-semibold); }
.my-profile__links { display: flex; gap: var(--space-md); }
</style>
```

- [ ] **Step 6:实现 `OnboardingPage.vue`(替换空壳)**

复用编辑页的三个部件(资料表单 / 标签 / 照片),提交后跳发现页:

```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { parseApiError } from '@/api/error'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import FormCard from '@/features/auth/FormCard.vue'
import PhotoGrid from '@/features/profile/PhotoGrid.vue'
import TagPicker from '@/features/profile/TagPicker.vue'
import { useProfileStore } from '@/stores/profile'

const router = useRouter()
const store = useProfileStore()

const nickname = ref('')
const gender = ref<'' | 'male' | 'female'>('')
const birthday = ref('')
const city = ref('')
const bio = ref('')
const tagIds = ref<number[]>([])
const error = ref('')

onMounted(async () => {
  if (!store.profile) await store.load().catch(() => {})
  const p = store.profile
  if (!p) return
  nickname.value = p.nickname
  gender.value = p.gender
  birthday.value = p.birthday ?? ''
  city.value = p.city
  bio.value = p.bio
  tagIds.value = p.tags.map((t) => t.id)
})

async function onSubmit() {
  error.value = ''
  try {
    await store.save({
      nickname: nickname.value,
      gender: gender.value || undefined,
      birthday: birthday.value || undefined,
      city: city.value,
      bio: bio.value,
      tag_ids: tagIds.value,
    })
    await router.push({ name: 'discovery' })
  } catch (e) {
    error.value = parseApiError(e).message
  }
}
</script>

<template>
  <FormCard title="完善资料" description="填完这些就可以开始滑卡了">
    <AppInput v-model="nickname" placeholder="昵称" :maxlength="20" :error="error" />
    <div class="onboarding__gender">
      <button
        v-for="option in [{ v: 'female', label: '女生' }, { v: 'male', label: '男生' }]"
        :key="option.v"
        type="button"
        class="onboarding__chip"
        :class="{ 'onboarding__chip--active': gender === option.v }"
        @click="gender = option.v as 'male' | 'female'"
      >
        {{ option.label }}
      </button>
    </div>
    <AppInput v-model="birthday" type="date" placeholder="生日" />
    <AppInput v-model="city" placeholder="城市" :maxlength="50" />
    <AppInput v-model="bio" placeholder="一句话介绍自己" :maxlength="200" />
    <TagPicker v-model="tagIds" />
    <PhotoGrid />
    <AppButton block size="lg" @click="onSubmit">开始使用</AppButton>
  </FormCard>
</template>

<style scoped>
.onboarding__gender { display: flex; gap: var(--space-sm); }
.onboarding__chip {
  flex: 1;
  height: 44px;
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-input);
  background: var(--color-bg-card);
  cursor: pointer;
}
.onboarding__chip--active { border-color: var(--color-brand); color: var(--color-brand); }
</style>
```

- [ ] **Step 7:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 8:提交**

```bash
git add web/src/features/profile web/src/features/onboarding web/src/router web/tests
git commit -m "feat(web): 我的页/完善资料页/封禁守卫"
```

**▶ 组 T4 检查点**:门禁全绿;真后端手测「编辑资料 → 上传照片 → 设置偏好 → 我的页显示完整度」。

---

## 组 T5:发现与配对(5 个任务)

### Task 5.1:发现 API 与 store

**Files:**
- Create: `web/src/api/discovery.ts`、`web/src/stores/discovery.ts`
- Modify: `web/src/api/types.ts`(追加 `Candidate` / `MatchSummary`)
- Test: `web/tests/unit/discovery-store.spec.ts`

**Interfaces:**
- Consumes: `http`、`parseApiError`、`Page<T>`(Task 4.1)。
- Produces:

```ts
// —— 追加到 src/api/types.ts ——
export interface Candidate {
  user_id: number
  nickname: string
  gender: Gender | ''
  age: number | null
  city: string
  bio: string
  tags: Tag[]
  photos: Photo[] // 只含已过审(discovery.md §3.1)
}
export interface MatchSummary {
  user_id: number
  im_user_id: string   // 形如 u9,聊天时用它
  nickname: string
  avatar_url: string | null
  matched_at: string   // ISO 8601
}
```

- `api/discovery.ts`:`fetchCandidates(limit = 10)`、`swipe(targetUserId, action)`、`fetchMatches(limit = 20, offset = 0)`
- `useDiscoveryStore()`:state `candidates` / `index` / `matched` / `matches` / `matchesCount` / `loading` / `submitting` / `error`;
  getters `current`(当前卡或 null)、`exhausted`;
  actions `loadCandidates()`、`decide(action)`、`dismissMatched()`、`loadMatches(reset = false)`
- **错误分支必须按接口文档处理**(discovery.md §3.2 错误码表):
  - `403`(轻封禁)→ 提示「账号已被限制,暂时无法滑卡」并**停在当前卡**
  - `404`(目标不存在)→ **跳过该卡**继续下一张
  - `429`(300 次/小时)→ 展示后端文案并停住

- [ ] **Step 1:写失败的测试**

`web/tests/unit/discovery-store.spec.ts`:

```ts
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { useDiscoveryStore } from '@/stores/discovery'
import { server } from '../support/server'

const card = (id: number) => ({
  user_id: id, nickname: `用户${id}`, gender: 'female', age: 25, city: '上海',
  bio: '', tags: [], photos: [{ id: id * 10, url: `https://cdn/${id}.jpg`, status: 'approved', order: 0 }],
})

function mockCandidates(ids: number[]) {
  server.use(mswHttp.get('/api/v1/discovery/candidates', () => HttpResponse.json(ids.map(card))))
}

describe('discovery store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('拉取候选卡并把第一张设为当前卡', async () => {
    mockCandidates([1, 2])
    const store = useDiscoveryStore()

    await store.loadCandidates()

    expect(store.candidates).toHaveLength(2)
    expect(store.current?.user_id).toBe(1)
    expect(store.exhausted).toBe(false)
  })

  it('滑完所有卡后 exhausted 为真', async () => {
    mockCandidates([1])
    server.use(mswHttp.post('/api/v1/discovery/swipe', () => HttpResponse.json({ matched: false })))
    const store = useDiscoveryStore()
    await store.loadCandidates()

    await store.decide('pass')

    expect(store.current).toBeNull()
    expect(store.exhausted).toBe(true)
  })

  it('互相喜欢时记录 matched,且配对对象就是刚滑的人', async () => {
    mockCandidates([7])
    server.use(mswHttp.post('/api/v1/discovery/swipe', () => HttpResponse.json({ matched: true })))
    const store = useDiscoveryStore()
    await store.loadCandidates()

    await store.decide('like')

    expect(store.matched?.user_id).toBe(7)
    store.dismissMatched()
    expect(store.matched).toBeNull()
  })

  it('轻封禁(403)时停在当前卡并给出提示', async () => {
    mockCandidates([1])
    server.use(
      mswHttp.post('/api/v1/discovery/swipe', () =>
        HttpResponse.json({ code: 40301, message: '账号已被限制,暂时无法滑卡', request_id: 'r' }, { status: 403 }),
      ),
    )
    const store = useDiscoveryStore()
    await store.loadCandidates()

    await store.decide('like')

    expect(store.error).toBe('账号已被限制,暂时无法滑卡')
    expect(store.current?.user_id).toBe(1) // 没有前进
  })

  it('目标已不存在(404)时跳过该卡', async () => {
    mockCandidates([1, 2])
    server.use(
      mswHttp.post('/api/v1/discovery/swipe', ({ request }) => {
        void request
        return HttpResponse.json({ code: 40401, message: '目标用户不存在', request_id: 'r' }, { status: 404 })
      }),
    )
    const store = useDiscoveryStore()
    await store.loadCandidates()

    await store.decide('like')

    expect(store.current?.user_id).toBe(2) // 前进到下一张
    expect(store.error).toBe('')
  })

  it('限流(429)按后端文案提示', async () => {
    mockCandidates([1])
    server.use(
      mswHttp.post('/api/v1/discovery/swipe', () =>
        HttpResponse.json({ code: 42902, message: '操作过于频繁,请稍后再试', request_id: 'r' }, { status: 429 }),
      ),
    )
    const store = useDiscoveryStore()
    await store.loadCandidates()

    await store.decide('like')

    expect(store.error).toBe('操作过于频繁,请稍后再试')
    expect(store.current?.user_id).toBe(1)
  })

  it('配对列表分页追加,不重置已有数据', async () => {
    const page1 = {
      count: 3,
      next: 'http://x/api/v1/matches?limit=2&offset=2',
      previous: null,
      results: [{ user_id: 1, im_user_id: 'u1', nickname: 'A', avatar_url: null, matched_at: '2026-10-01T00:00:00Z' }],
    }
    const page2 = {
      count: 3, next: null, previous: null,
      results: [{ user_id: 2, im_user_id: 'u2', nickname: 'B', avatar_url: null, matched_at: '2026-10-02T00:00:00Z' }],
    }
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/matches', () => {
        calls += 1
        return HttpResponse.json(calls === 1 ? page1 : page2)
      }),
    )
    const store = useDiscoveryStore()

    await store.loadMatches()
    await store.loadMatches()

    expect(store.matches.map((m) => m.user_id)).toEqual([1, 2])
    expect(store.matchesCount).toBe(3)
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/unit/discovery-store.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现 `api/discovery.ts`**

```ts
import { http } from './http'
import type { Candidate, MatchSummary, Page } from './types'

export async function fetchCandidates(limit = 10): Promise<Candidate[]> {
  const { data } = await http.get('/discovery/candidates', { params: { limit } })
  return data as Candidate[]
}

/** 幂等:重复提交同一目标,matched 返回值不变。 */
export async function swipe(
  targetUserId: number,
  action: 'like' | 'pass',
): Promise<{ matched: boolean }> {
  const { data } = await http.post('/discovery/swipe', {
    target_user_id: targetUserId,
    action,
  })
  return { matched: Boolean(data.matched) }
}

export async function fetchMatches(limit = 20, offset = 0): Promise<Page<MatchSummary>> {
  const { data } = await http.get('/matches', { params: { limit, offset } })
  return data as Page<MatchSummary>
}
```

- [ ] **Step 4:实现 `stores/discovery.ts`**

```ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as discoveryApi from '@/api/discovery'
import { parseApiError } from '@/api/error'
import type { Candidate, MatchSummary } from '@/api/types'

const MATCHES_PAGE_SIZE = 20

export const useDiscoveryStore = defineStore('discovery', () => {
  const candidates = ref<Candidate[]>([])
  const index = ref(0)
  const matched = ref<Candidate | null>(null)
  const matches = ref<MatchSummary[]>([])
  const matchesCount = ref(0)
  const matchesOffset = ref(0)
  const loading = ref(false)
  const submitting = ref(false)
  const error = ref('')

  const current = computed<Candidate | null>(() => candidates.value[index.value] ?? null)
  const exhausted = computed(() => !loading.value && current.value === null)

  async function loadCandidates(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      candidates.value = await discoveryApi.fetchCandidates()
      index.value = 0
    } catch (e) {
      error.value = parseApiError(e).message
    } finally {
      loading.value = false
    }
  }

  async function decide(action: 'like' | 'pass'): Promise<void> {
    const target = current.value
    if (!target || submitting.value) return
    submitting.value = true
    error.value = ''
    try {
      const result = await discoveryApi.swipe(target.user_id, action)
      index.value += 1
      if (result.matched) matched.value = target
    } catch (e) {
      const apiError = parseApiError(e)
      if (apiError.status === 404) {
        // 目标不存在/已不可见:跳过这张卡,不打扰用户(discovery.md §3.2)
        index.value += 1
      } else {
        error.value = apiError.message
      }
    } finally {
      submitting.value = false
    }
  }

  function dismissMatched(): void {
    matched.value = null
  }

  async function loadMatches(reset = false): Promise<void> {
    if (reset) {
      matches.value = []
      matchesOffset.value = 0
    }
    const page = await discoveryApi.fetchMatches(MATCHES_PAGE_SIZE, matchesOffset.value)
    matches.value = [...matches.value, ...page.results]
    matchesCount.value = page.count
    matchesOffset.value += page.results.length
  }

  return {
    candidates, index, matched, matches, matchesCount, loading, submitting, error,
    current, exhausted, loadCandidates, decide, dismissMatched, loadMatches,
  }
})
```

- [ ] **Step 5:跑测试确认通过** → Run: `cd web && npm run test:run tests/unit/discovery-store.spec.ts && npm run type-check`;Expected: 7 passed

- [ ] **Step 6:提交**

```bash
git add web/src/api web/src/stores web/tests/unit
git commit -m "feat(web): 发现与配对 API/store(403 停住、404 跳过、429 提示)"
```

### Task 5.2:候选卡组件

**Files:**
- Create: `web/src/features/discovery/CandidateCard.vue`
- Test: `web/tests/component/candidate-card.spec.ts`

**Interfaces:**
- Consumes: `Candidate`(Task 5.1)、`AppAvatar`。
- Produces:`CandidateCard.vue` —— props `{ candidate: Candidate; online?: boolean }`(默认 `false`,在线光在 Task 8.4 接线);照片全出血 + 底部 scrim 叠字(心跳附录 A.2);标签最多显示 3 个。

- [ ] **Step 1:写失败的测试**

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CandidateCard from '@/features/discovery/CandidateCard.vue'

const candidate = {
  user_id: 8, nickname: '小雨', gender: 'female', age: 26, city: '上海', bio: '喜欢爬山',
  tags: [
    { id: 1, name: '旅行', icon: 'plane' },
    { id: 2, name: '电影', icon: 'film' },
    { id: 3, name: '咖啡', icon: 'coffee' },
    { id: 4, name: '摄影', icon: 'camera' },
  ],
  photos: [{ id: 1, url: 'https://cdn/a.jpg', status: 'approved', order: 0 }],
}

describe('CandidateCard', () => {
  it('展示照片、昵称年龄城市与最多 3 个标签', () => {
    const w = mount(CandidateCard, { props: { candidate } })
    expect(w.find('.candidate-card__photo').attributes('src')).toBe('https://cdn/a.jpg')
    expect(w.text()).toContain('小雨')
    expect(w.text()).toContain('26')
    expect(w.text()).toContain('上海')
    expect(w.findAll('.candidate-card__tag')).toHaveLength(3)
  })

  it('没有照片时用头像首字兜底', () => {
    const w = mount(CandidateCard, { props: { candidate: { ...candidate, photos: [] } } })
    expect(w.find('.candidate-card__photo').exists()).toBe(false)
    expect(w.find('.candidate-card__fallback').exists()).toBe(true)
  })

  it('在线时才渲染在线光', () => {
    expect(mount(CandidateCard, { props: { candidate, online: true } }).find('.candidate-card__online').exists()).toBe(true)
    expect(mount(CandidateCard, { props: { candidate } }).find('.candidate-card__online').exists()).toBe(false)
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/component/candidate-card.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现**

```vue
<script setup lang="ts">
import { computed } from 'vue'
import type { Candidate } from '@/api/types'

const props = withDefaults(defineProps<{ candidate: Candidate; online?: boolean }>(), { online: false })

const photoUrl = computed(() => props.candidate.photos[0]?.url ?? null)
const tags = computed(() => props.candidate.tags.slice(0, 3))
const meta = computed(() =>
  [props.candidate.age ? `${props.candidate.age} 岁` : '', props.candidate.city]
    .filter(Boolean)
    .join(' · '),
)
</script>

<template>
  <article class="candidate-card">
    <img v-if="photoUrl" class="candidate-card__photo" :src="photoUrl" alt="" />
    <div v-else class="candidate-card__fallback">{{ props.candidate.nickname.charAt(0) || '♥' }}</div>

    <span v-if="props.online" class="candidate-card__online" aria-label="在线" />

    <div class="candidate-card__scrim">
      <h2 class="candidate-card__name">
        {{ props.candidate.nickname || '这个人很神秘' }}
      </h2>
      <p v-if="meta" class="candidate-card__meta">{{ meta }}</p>
      <p v-if="props.candidate.bio" class="candidate-card__bio">{{ props.candidate.bio }}</p>
      <div v-if="tags.length" class="candidate-card__tags">
        <span v-for="tag in tags" :key="tag.id" class="candidate-card__tag">{{ tag.name }}</span>
      </div>
    </div>
  </article>
</template>

<style scoped>
.candidate-card {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  border-radius: var(--radius-discovery-card);
  background: var(--color-divider);
}
.candidate-card__photo { width: 100%; height: 100%; object-fit: cover; }
.candidate-card__fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  background: var(--gradient-heart);
  color: var(--color-bg-card);
  font-size: var(--text-emoji);
}
.candidate-card__online {
  position: absolute;
  top: var(--space-lg);
  right: var(--space-lg);
  width: 12px;
  height: 12px;
  border: 2px solid var(--color-bg-card);
  border-radius: var(--radius-full);
  background: var(--color-green);
  box-shadow: 0 0 0 4px rgb(18 196 139 / 35%);
}
/* 照片叠字:透明 → photoScrim 的底部渐变(附录 A.2) */
.candidate-card__scrim {
  position: absolute;
  inset: auto 0 0 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  padding: var(--space-xl) var(--space-lg) var(--space-lg);
  background: linear-gradient(to bottom, transparent, var(--color-photo-scrim));
  color: var(--color-bg-card);
}
.candidate-card__name { margin: 0; font-size: var(--text-title); font-weight: var(--weight-bold); }
.candidate-card__meta { margin: 0; font-size: var(--text-caption); opacity: 0.9; }
.candidate-card__bio { margin: 0; font-size: var(--text-caption); opacity: 0.85; }
.candidate-card__tags { display: flex; flex-wrap: wrap; gap: var(--space-xs); margin-top: var(--space-xs); }
.candidate-card__tag {
  padding: 2px var(--space-sm);
  border-radius: var(--radius-full);
  background: rgb(255 255 255 / 22%);
  font-size: var(--text-badge);
}
</style>
```

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 5:提交**

```bash
git add web/src/features/discovery web/tests/component
git commit -m "feat(web): 候选卡组件(照片全出血 + scrim 叠字)"
```

### Task 5.3:滑卡判定(纯函数)与滑卡台

**Files:**
- Create: `web/src/features/discovery/swipe.ts`、`web/src/features/discovery/SwipeDeck.vue`
- Test: `web/tests/unit/swipe.spec.ts`、`web/tests/component/swipe-deck.spec.ts`

**Interfaces:**
- Consumes: `useDiscoveryStore()`、`CandidateCard`。
- Produces:
  - `swipe.ts`:`SWIPE_THRESHOLD = 120`(px)、`swipeDirection(dx: number): 'like' | 'pass' | null`(超过阈值才判定,`dx > 0` 为 like)**纯函数,单独单测** —— 拖拽的指针事件在 jsdom 里不可靠,把判定逻辑抽出来才测得准
  - `SwipeDeck.vue`:props `{ candidate: Candidate | null; submitting?: boolean }`;emits `decide: ['like' | 'pass']`;**三种操作入口共用 `decide`**:拖拽过阈值、键盘 `←`/`→`、两个圆钮

- [ ] **Step 1:写失败的测试**

`web/tests/unit/swipe.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { SWIPE_THRESHOLD, swipeDirection } from '@/features/discovery/swipe'

describe('swipeDirection', () => {
  it('未超过阈值不判定', () => {
    expect(swipeDirection(0)).toBeNull()
    expect(swipeDirection(SWIPE_THRESHOLD - 1)).toBeNull()
    expect(swipeDirection(-(SWIPE_THRESHOLD - 1))).toBeNull()
  })

  it('右滑是喜欢,左滑是跳过', () => {
    expect(swipeDirection(SWIPE_THRESHOLD)).toBe('like')
    expect(swipeDirection(400)).toBe('like')
    expect(swipeDirection(-SWIPE_THRESHOLD)).toBe('pass')
    expect(swipeDirection(-400)).toBe('pass')
  })
})
```

`web/tests/component/swipe-deck.spec.ts`:

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SwipeDeck from '@/features/discovery/SwipeDeck.vue'

const candidate = {
  user_id: 8, nickname: '小雨', gender: 'female', age: 26, city: '上海', bio: '',
  tags: [], photos: [{ id: 1, url: 'https://cdn/a.jpg', status: 'approved', order: 0 }],
}

describe('SwipeDeck', () => {
  it('点「喜欢」圆钮派发 decide(like)', async () => {
    const w = mount(SwipeDeck, { props: { candidate } })
    await w.find('.swipe-deck__like').trigger('click')
    expect(w.emitted('decide')?.[0]).toEqual(['like'])
  })

  it('点「不喜欢」圆钮派发 decide(pass)', async () => {
    const w = mount(SwipeDeck, { props: { candidate } })
    await w.find('.swipe-deck__pass').trigger('click')
    expect(w.emitted('decide')?.[0]).toEqual(['pass'])
  })

  it('键盘左右方向键与圆钮走同一处理函数', async () => {
    const w = mount(SwipeDeck, { props: { candidate }, attachTo: document.body })
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }))
    expect(w.emitted('decide')).toEqual([['like'], ['pass']])
    w.unmount()
  })

  it('没有卡片时不渲染操作区', () => {
    const w = mount(SwipeDeck, { props: { candidate: null } })
    expect(w.find('.swipe-deck__actions').exists()).toBe(false)
  })

  it('submitting 时不重复派发', async () => {
    const w = mount(SwipeDeck, { props: { candidate, submitting: true } })
    await w.find('.swipe-deck__like').trigger('click')
    expect(w.emitted('decide')).toBeUndefined()
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/unit/swipe.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现 `swipe.ts` 与 `SwipeDeck.vue`**

`web/src/features/discovery/swipe.ts`:

```ts
/** 拖动多少像素才算一次滑卡(超过即判定,避免误触)。 */
export const SWIPE_THRESHOLD = 120

/** 纯函数:根据水平位移给出动作;未过阈值返回 null。 */
export function swipeDirection(dx: number): 'like' | 'pass' | null {
  if (dx >= SWIPE_THRESHOLD) return 'like'
  if (dx <= -SWIPE_THRESHOLD) return 'pass'
  return null
}
```

`web/src/features/discovery/SwipeDeck.vue`:

```vue
<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import type { Candidate } from '@/api/types'
import CandidateCard from './CandidateCard.vue'
import { swipeDirection } from './swipe'

const props = withDefaults(
  defineProps<{ candidate: Candidate | null; submitting?: boolean }>(),
  { submitting: false },
)
const emit = defineEmits<{ decide: ['like' | 'pass'] }>()

const offsetX = ref(0)
const dragging = ref(false)
let startX = 0

function decide(action: 'like' | 'pass') {
  if (props.submitting) return
  emit('decide', action)
}

function onPointerDown(event: PointerEvent) {
  if (props.submitting) return
  dragging.value = true
  startX = event.clientX
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
}

function onPointerMove(event: PointerEvent) {
  if (!dragging.value) return
  offsetX.value = event.clientX - startX
}

function onPointerUp() {
  dragging.value = false
  const action = swipeDirection(offsetX.value)
  offsetX.value = 0
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
  if (action) decide(action)
}

function onKeydown(event: KeyboardEvent) {
  // 输入框里按方向键不该触发滑卡
  const target = event.target as HTMLElement | null
  if (target && ['INPUT', 'TEXTAREA'].includes(target.tagName)) return
  if (event.key === 'ArrowRight') decide('like')
  if (event.key === 'ArrowLeft') decide('pass')
}

window.addEventListener('keydown', onKeydown)
onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
})

// 换卡时复位位移与动画状态
watch(() => props.candidate?.user_id, () => {
  offsetX.value = 0
})

const cardStyle = computed(() => ({
  transform: `translateX(${offsetX.value}px) rotate(${offsetX.value / 24}deg)`,
  transition: dragging.value ? 'none' : 'transform var(--motion-base) var(--ease-out)',
}))
</script>

<template>
  <div class="swipe-deck">
    <div v-if="props.candidate" class="swipe-deck__stage" :style="cardStyle" @pointerdown="onPointerDown">
      <CandidateCard :candidate="props.candidate" />
    </div>

    <div v-if="props.candidate" class="swipe-deck__actions">
      <button
        type="button"
        class="swipe-deck__button swipe-deck__pass"
        aria-label="不喜欢"
        :disabled="props.submitting"
        @click="decide('pass')"
      >
        ✕
      </button>
      <button
        type="button"
        class="swipe-deck__button swipe-deck__like"
        aria-label="喜欢"
        :disabled="props.submitting"
        @click="decide('like')"
      >
        ♥
      </button>
    </div>
  </div>
</template>

<style scoped>
.swipe-deck {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-lg);
  height: 100%;
  min-height: 0;
}
/* 卡片按可用高度定尺(spec §6.3):宽高比锁 3:4,窗口矮就整体缩小 */
.swipe-deck__stage {
  flex: 1;
  min-height: 0;
  aspect-ratio: 3 / 4;
  max-width: 100%;
  cursor: grab;
}
.swipe-deck__stage:active { cursor: grabbing; }
.swipe-deck__actions { display: flex; gap: var(--space-xl); flex: none; }
.swipe-deck__button {
  width: 56px;
  height: 56px;
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-card);
  font-size: var(--text-title);
  cursor: pointer;
  transition: transform var(--motion-fast) var(--ease-out), color var(--motion-fast) var(--ease-out);
}
.swipe-deck__button:not(:disabled):hover { transform: translateY(-2px); }
.swipe-deck__button:disabled { opacity: 0.5; cursor: not-allowed; }
.swipe-deck__pass:not(:disabled):hover { color: var(--color-text2); }
.swipe-deck__like:not(:disabled):hover { color: var(--color-brand); }
</style>
```

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 5:提交**

```bash
git add web/src/features/discovery web/tests
git commit -m "feat(web): 滑卡台(拖拽阈值/键盘/圆钮共用判定)"
```

### Task 5.4:配对列表

**Files:**
- Create: `web/src/features/discovery/MatchesList.vue`
- Test: `web/tests/component/matches-list.spec.ts`

**Interfaces:**
- Consumes: `useDiscoveryStore().matches` / `matchesCount` / `loadMatches(reset)`、`AppAvatar`。
- Produces:`MatchesList.vue` —— 横滑头像条 + 「加载更多」;点某人 → `/chat/:peerId`(**注意用 `im_user_id` 作为 `peerId`**,与 App 的会话主键一致)。

- [ ] **Step 1:写失败的测试**

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import MatchesList from '@/features/discovery/MatchesList.vue'
import { server } from '../support/server'

const page = {
  count: 3, next: null, previous: null,
  results: [
    { user_id: 1, im_user_id: 'u1', nickname: 'A', avatar_url: null, matched_at: '2026-10-01T00:00:00Z' },
    { user_id: 2, im_user_id: 'u2', nickname: 'B', avatar_url: 'https://cdn/b.jpg', matched_at: '2026-10-02T00:00:00Z' },
  ],
}

describe('MatchesList', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('挂载即拉取并渲染配对头像', async () => {
    server.use(mswHttp.get('/api/v1/matches', () => HttpResponse.json(page)))
    const w = mount(MatchesList, {
      global: { plugins: [createPinia()], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    expect(w.findAll('.matches-list__item')).toHaveLength(2)
    expect(w.text()).toContain('A')
  })

  it('还有下一页时展示「加载更多」,点后追加', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/matches', () => {
        calls += 1
        return HttpResponse.json(
          calls === 1
            ? { ...page, next: 'http://x/api/v1/matches?offset=2' }
            : { count: 3, next: null, previous: null, results: [{ user_id: 3, im_user_id: 'u3', nickname: 'C', avatar_url: null, matched_at: '2026-10-03T00:00:00Z' }] },
        )
      }),
    )
    const w = mount(MatchesList, {
      global: { plugins: [createPinia()], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    await w.find('.matches-list__more').trigger('click')
    await flushPromises()

    expect(w.findAll('.matches-list__item')).toHaveLength(3)
  })

  it('一个配对都没有时不渲染区块', async () => {
    server.use(mswHttp.get('/api/v1/matches', () => HttpResponse.json({ count: 0, next: null, previous: null, results: [] })))
    const w = mount(MatchesList, {
      global: { plugins: [createPinia()], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    expect(w.find('.matches-list').exists()).toBe(false)
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/component/matches-list.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现**

```vue
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppAvatar from '@/components/AppAvatar.vue'
import { useDiscoveryStore } from '@/stores/discovery'

const store = useDiscoveryStore()
const busy = ref(false)

const hasMore = computed(() => store.matches.length < store.matchesCount)

onMounted(() => {
  store.loadMatches().catch(() => {})
})

async function loadMore() {
  busy.value = true
  try {
    await store.loadMatches()
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section v-if="store.matches.length" class="matches-list">
    <h2 class="matches-list__title">我的配对 · {{ store.matchesCount }}</h2>
    <div class="matches-list__row">
      <RouterLink
        v-for="match in store.matches"
        :key="match.user_id"
        class="matches-list__item"
        :to="{ name: 'chat', params: { peerId: match.im_user_id } }"
      >
        <AppAvatar :src="match.avatar_url" :name="match.nickname" :size="48" />
        <span class="matches-list__name">{{ match.nickname || '神秘人' }}</span>
      </RouterLink>
      <button v-if="hasMore" type="button" class="matches-list__more" :disabled="busy" @click="loadMore">
        加载更多
      </button>
    </div>
  </section>
</template>

<style scoped>
.matches-list { display: flex; flex-direction: column; gap: var(--space-sm); }
.matches-list__title { margin: 0; font-size: var(--text-caption); color: var(--color-text2); }
.matches-list__row {
  display: flex;
  gap: var(--space-md);
  overflow-x: auto;
  padding-bottom: var(--space-xs);
}
.matches-list__item {
  display: flex;
  flex: none;
  flex-direction: column;
  align-items: center;
  gap: var(--space-xs);
  width: 64px;
}
.matches-list__name {
  max-width: 64px;
  overflow: hidden;
  font-size: var(--text-badge);
  color: var(--color-text2);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.matches-list__more {
  flex: none;
  align-self: center;
  height: 32px;
  padding: 0 var(--space-md);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  font-size: var(--text-caption);
  cursor: pointer;
}
</style>
```

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 5:提交**

```bash
git add web/src/features/discovery web/tests/component
git commit -m "feat(web): 配对列表(横滑条 + 分页加载)"
```

### Task 5.5:发现页组装与配对情感时刻

**Files:**
- Create: `web/src/features/discovery/MatchMoment.vue`
- Modify: `web/src/features/discovery/DiscoveryPage.vue`(替换空壳)
- Test: `web/tests/component/match-moment.spec.ts`、`web/tests/component/discovery-page.spec.ts`

**Interfaces:**
- Consumes: `useDiscoveryStore()`、`SwipeDeck`、`MatchesList`、`AppEmpty`、`AppErrorView`。
- Produces:
  - `MatchMoment.vue`:props `{ candidate: Candidate }`;emits `close`、`chat`;心跳渐变背景 + 「你们互相喜欢」+ 两个按钮(去聊天 → `/chat/:im_user_id`、继续滑 → close)
  - `DiscoveryPage.vue`:顶部配对列表 + 中部滑卡台 + 四态(加载/空/错误/正常)+ 轻封禁提示

- [ ] **Step 1:写失败的测试**

`web/tests/component/match-moment.spec.ts`:

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MatchMoment from '@/features/discovery/MatchMoment.vue'

const candidate = {
  user_id: 8, nickname: '小雨', gender: 'female', age: 26, city: '上海', bio: '', tags: [],
  photos: [{ id: 1, url: 'https://cdn/a.jpg', status: 'approved', order: 0 }],
}

describe('MatchMoment', () => {
  it('展示配对文案与对方昵称', () => {
    const w = mount(MatchMoment, {
      props: { candidate },
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    expect(w.text()).toContain('你们互相喜欢')
    expect(w.text()).toContain('小雨')
  })

  it('「继续滑」派发 close', async () => {
    const w = mount(MatchMoment, {
      props: { candidate },
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await w.find('.match-moment__close').trigger('click')
    expect(w.emitted('close')).toHaveLength(1)
  })
})
```

`web/tests/component/discovery-page.spec.ts`:

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import DiscoveryPage from '@/features/discovery/DiscoveryPage.vue'
import { server } from '../support/server'

const card = {
  user_id: 8, nickname: '小雨', gender: 'female', age: 26, city: '上海', bio: '', tags: [],
  photos: [{ id: 1, url: 'https://cdn/a.jpg', status: 'approved', order: 0 }],
}

function mountPage() {
  return mount(DiscoveryPage, {
    global: { plugins: [createPinia()], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
}

describe('DiscoveryPage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('没有候选时展示空态', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', () => HttpResponse.json([])),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json({ count: 0, next: null, previous: null, results: [] })),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.app-empty').exists()).toBe(true)
  })

  it('有候选时渲染滑卡台', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', () => HttpResponse.json([card])),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json({ count: 0, next: null, previous: null, results: [] })),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.swipe-deck').exists()).toBe(true)
    expect(w.text()).toContain('小雨')
  })

  it('拉取失败时展示错误态并可重试', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', () => {
        calls += 1
        return calls === 1
          ? HttpResponse.json({ code: 50002, message: '服务器开小差了', request_id: 'r' }, { status: 500 })
          : HttpResponse.json([card])
      }),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json({ count: 0, next: null, previous: null, results: [] })),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.app-error').exists()).toBe(true)
    await w.find('.app-error button').trigger('click')
    await flushPromises()
    expect(w.find('.swipe-deck').exists()).toBe(true)
  })

  it('互相喜欢时弹出情感时刻', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', () => HttpResponse.json([card])),
      mswHttp.post('/api/v1/discovery/swipe', () => HttpResponse.json({ matched: true })),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json({ count: 0, next: null, previous: null, results: [] })),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('.swipe-deck__like').trigger('click')
    await flushPromises()

    expect(w.find('.match-moment').exists()).toBe(true)
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/component/match-moment.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现 `MatchMoment.vue`**

```vue
<script setup lang="ts">
import type { Candidate } from '@/api/types'

const props = defineProps<{ candidate: Candidate }>()
defineEmits<{ close: []; chat: [] }>()
</script>

<template>
  <div class="match-moment" role="dialog" aria-modal="true">
    <div class="match-moment__panel">
      <span class="match-moment__heart">♥</span>
      <h2 class="match-moment__title">你们互相喜欢</h2>
      <p class="match-moment__desc">和 {{ props.candidate.nickname || '对方' }} 打个招呼吧</p>
      <RouterLink
        class="match-moment__chat"
        :to="{ name: 'chat', params: { peerId: `u${props.candidate.user_id}` } }"
      >
        去聊天
      </RouterLink>
      <button type="button" class="match-moment__close" @click="$emit('close')">继续滑</button>
    </div>
  </div>
</template>

<style scoped>
.match-moment {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gradient-heart);
}
.match-moment__panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-md);
  width: clamp(320px, 40%, var(--form-card-max));
  padding: var(--space-xxl);
  border-radius: var(--radius-sheet);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-floating-bar);
  text-align: center;
}
.match-moment__heart { font-size: var(--text-emoji); color: var(--color-brand); }
.match-moment__title { margin: 0; font-size: var(--text-display); font-weight: var(--weight-extrabold); }
.match-moment__desc { margin: 0; font-size: var(--text-caption); color: var(--color-text2); }
.match-moment__chat {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 52px;
  border-radius: var(--radius-input);
  background: var(--gradient-heart);
  color: var(--color-bg-card);
  font-weight: var(--weight-semibold);
  box-shadow: var(--shadow-primary-button);
}
.match-moment__close {
  border: none;
  background: none;
  color: var(--color-text2);
  font-size: var(--text-caption);
  cursor: pointer;
}
</style>
```

- [ ] **Step 4:实现 `DiscoveryPage.vue`(替换空壳)**

```vue
<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import AppEmpty from '@/components/AppEmpty.vue'
import AppErrorView from '@/components/AppErrorView.vue'
import AppSkeleton from '@/components/AppSkeleton.vue'
import { useDiscoveryStore } from '@/stores/discovery'
import MatchesList from './MatchesList.vue'
import MatchMoment from './MatchMoment.vue'
import SwipeDeck from './SwipeDeck.vue'

const store = useDiscoveryStore()
const router = useRouter()

const showEmpty = computed(() => !store.loading && !store.error && store.exhausted)

onMounted(() => {
  store.loadCandidates()
})

async function onDecide(action: 'like' | 'pass') {
  await store.decide(action)
}

function onChat() {
  const target = store.matched
  store.dismissMatched()
  if (target) router.push({ name: 'chat', params: { peerId: `u${target.user_id}` } })
}
</script>

<template>
  <section class="discovery">
    <MatchesList />

    <p v-if="store.error" class="discovery__error">{{ store.error }}</p>

    <AppSkeleton v-if="store.loading" height="520px" radius="var(--radius-discovery-card)" />

    <AppErrorView
      v-else-if="store.error && store.candidates.length === 0"
      :message="store.error"
      @retry="store.loadCandidates()"
    />

    <AppEmpty
      v-else-if="showEmpty"
      emoji="🫧"
      title="附近的卡都滑完了"
      description="过一会儿再来看看,或者去广场逛逛"
    />

    <SwipeDeck
      v-else
      :candidate="store.current"
      :submitting="store.submitting"
      @decide="onDecide"
    />

    <MatchMoment v-if="store.matched" :candidate="store.matched" @close="store.dismissMatched()" @chat="onChat" />
  </section>
</template>

<style scoped>
.discovery {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  height: 100%;
  min-height: 0;
  padding: var(--space-lg) var(--space-section-gap);
}
.discovery__error { margin: 0; font-size: var(--text-caption); color: var(--color-danger); }
</style>
```

- [ ] **Step 5:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 6:真后端目检**

Run: `cd chatapp && python manage.py runserver` + `cd web && npm run dev`
目检:滑卡三种操作都能用;右滑喜欢 + 对方也喜欢过你 → 弹出「你们互相喜欢」;点「去聊天」跳到聊天页(此时聊天页还是空壳)。

- [ ] **Step 7:提交**

```bash
git add web/src/features/discovery web/tests
git commit -m "feat(web): 发现页组装与配对情感时刻"
```

**▶ 组 T5 检查点**:门禁全绿;真后端手测滑卡与配对情感时刻。

---

## 组 T7:广场(6 个任务)

### Task 7.1:广场 API 与 store

**Files:**
- Create: `web/src/api/feed.ts`、`web/src/stores/feed.ts`
- Modify: `web/src/api/types.ts`(追加动态与评论类型)
- Test: `web/tests/unit/feed-store.spec.ts`

**Interfaces:**
- Consumes: `http`、`Page<T>`。
- Produces:

```ts
// —— 追加到 src/api/types.ts ——
export interface PostAuthor { user_id: number; nickname: string; avatar_url: string | null }
export interface Post {
  id: number
  author: PostAuthor
  text: string
  images: string[]          // 完整 URL,最多 9 张
  like_count: number
  comment_count: number
  liked_by_me: boolean
  created_at: string        // ISO 8601
}
export interface Comment { id: number; author: PostAuthor; text: string; created_at: string }
export type ReportType = 'harassment' | 'porn' | 'fraud' | 'other'
```

- `api/feed.ts`:`fetchPosts(limit, offset)`、`fetchMyPosts(limit, offset)`、`fetchPost(id)`、`createPost(text, images)`、`deletePost(id)`、`likePost(id)`、`unlikePost(id)`、`fetchComments(postId, limit, offset)`、`createComment(postId, text)`、`reportPost(postId, type, detail)`
- `useFeedStore()`:state `posts` / `count` / `loading` / `loadingMore` / `error`;getters `hasMore`;
  actions `load(reset)`、`loadMine(reset)`、`toggleLike(post)`、`removePost(id)`、`prepend(post)`、`create(text, images)`

- [ ] **Step 1:写失败的测试**

`web/tests/unit/feed-store.spec.ts`:

```ts
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { useFeedStore } from '@/stores/feed'
import { server } from '../support/server'

export const post = (id: number, liked = false) => ({
  id,
  author: { user_id: 3, nickname: '小雨', avatar_url: null },
  text: `第 ${id} 条`,
  images: [],
  like_count: liked ? 1 : 0,
  comment_count: 0,
  liked_by_me: liked,
  created_at: '2026-10-01T10:00:00Z',
})

const paged = (results: unknown[], overrides: Record<string, unknown> = {}) => ({
  count: results.length, next: null, previous: null, results, ...overrides,
})

describe('feed store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('分页追加而不是替换', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/posts', () => {
        calls += 1
        return HttpResponse.json(calls === 1 ? paged([post(1)], { count: 2, next: 'x' }) : paged([post(2)], { count: 2 }))
      }),
    )
    const store = useFeedStore()

    await store.load()
    await store.load()

    expect(store.posts.map((p) => p.id)).toEqual([1, 2])
  })

  it('点赞先行更新界面,失败时回滚', async () => {
    server.use(
      mswHttp.get('/api/v1/posts', () => HttpResponse.json(paged([post(1)]))),
      mswHttp.post('/api/v1/posts/1/like', () =>
        HttpResponse.json({ code: 50002, message: '服务器开小差了', request_id: 'r' }, { status: 500 }),
      ),
    )
    const store = useFeedStore()
    await store.load()

    await store.toggleLike(store.posts[0])

    expect(store.posts[0].liked_by_me).toBe(false) // 已回滚
    expect(store.posts[0].like_count).toBe(0)
  })

  it('点赞成功后计数 +1', async () => {
    server.use(
      mswHttp.get('/api/v1/posts', () => HttpResponse.json(paged([post(1)]))),
      mswHttp.post('/api/v1/posts/1/like', () => HttpResponse.json({ liked: true })),
    )
    const store = useFeedStore()
    await store.load()

    await store.toggleLike(store.posts[0])

    expect(store.posts[0].liked_by_me).toBe(true)
    expect(store.posts[0].like_count).toBe(1)
  })

  it('取消点赞走 DELETE 并把计数减回去', async () => {
    server.use(
      mswHttp.get('/api/v1/posts', () => HttpResponse.json(paged([post(1, true)]))),
      mswHttp.delete('/api/v1/posts/1/like', () => HttpResponse.json({ liked: false })),
    )
    const store = useFeedStore()
    await store.load()

    await store.toggleLike(store.posts[0])

    expect(store.posts[0].liked_by_me).toBe(false)
    expect(store.posts[0].like_count).toBe(0)
  })

  it('发布成功后新动态插到最前', async () => {
    server.use(
      mswHttp.get('/api/v1/posts', () => HttpResponse.json(paged([post(1)]))),
      mswHttp.post('/api/v1/posts', () => HttpResponse.json(post(99))),
    )
    const store = useFeedStore()
    await store.load()

    await store.create('新动态', [])

    expect(store.posts[0].id).toBe(99)
    expect(store.count).toBe(2)
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/unit/feed-store.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现 `api/feed.ts`**

```ts
import { http } from './http'
import type { Comment, Page, Post, ReportType } from './types'

export async function fetchPosts(limit = 20, offset = 0): Promise<Page<Post>> {
  const { data } = await http.get('/posts', { params: { limit, offset } })
  return data as Page<Post>
}

export async function fetchMyPosts(limit = 20, offset = 0): Promise<Page<Post>> {
  const { data } = await http.get('/posts/mine', { params: { limit, offset } })
  return data as Page<Post>
}

export async function fetchPost(id: number): Promise<Post> {
  const { data } = await http.get(`/posts/${id}`)
  return data as Post
}

/** 图片字段名固定为 images,多次追加同名 part(feed.md §5.2)。 */
export async function createPost(text: string, images: File[]): Promise<Post> {
  const form = new FormData()
  if (text) form.append('text', text)
  images.forEach((file) => form.append('images', file))
  const { data } = await http.post('/posts', form)
  return data as Post
}

export async function deletePost(id: number): Promise<void> {
  await http.delete(`/posts/${id}`)
}

export async function likePost(id: number): Promise<void> {
  await http.post(`/posts/${id}/like`)
}

export async function unlikePost(id: number): Promise<void> {
  await http.delete(`/posts/${id}/like`)
}

export async function fetchComments(postId: number, limit = 20, offset = 0): Promise<Page<Comment>> {
  const { data } = await http.get(`/posts/${postId}/comments`, { params: { limit, offset } })
  return data as Page<Comment>
}

export async function createComment(postId: number, text: string): Promise<Comment> {
  const { data } = await http.post(`/posts/${postId}/comments`, { text })
  return data as Comment
}

export async function reportPost(postId: number, type: ReportType, detail = ''): Promise<void> {
  await http.post(`/posts/${postId}/report`, { type, detail })
}
```

- [ ] **Step 4:实现 `stores/feed.ts`**

```ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as feedApi from '@/api/feed'
import { parseApiError } from '@/api/error'
import type { Post } from '@/api/types'

const PAGE_SIZE = 20

export const useFeedStore = defineStore('feed', () => {
  const posts = ref<Post[]>([])
  const count = ref(0)
  const offset = ref(0)
  const loading = ref(false)
  const loadingMore = ref(false)
  const error = ref('')

  const hasMore = computed(() => posts.value.length < count.value)

  async function loadPage(fetcher: typeof feedApi.fetchPosts, reset: boolean): Promise<void> {
    if (reset) {
      posts.value = []
      offset.value = 0
    }
    const isFirst = posts.value.length === 0
    if (isFirst) loading.value = true
    else loadingMore.value = true
    error.value = ''
    try {
      const page = await fetcher(PAGE_SIZE, offset.value)
      posts.value = [...posts.value, ...page.results]
      count.value = page.count
      offset.value += page.results.length
    } catch (e) {
      error.value = parseApiError(e).message
    } finally {
      loading.value = false
      loadingMore.value = false
    }
  }

  const load = (reset = false) => loadPage(feedApi.fetchPosts, reset)
  const loadMine = (reset = false) => loadPage(feedApi.fetchMyPosts, reset)

  /** 乐观更新:先改界面,失败回滚(feed.md 的点赞是无副作用的幂等操作)。 */
  async function toggleLike(target: Post): Promise<void> {
    const index = posts.value.findIndex((p) => p.id === target.id)
    if (index < 0) return
    const before = { ...posts.value[index] }
    posts.value[index] = {
      ...before,
      liked_by_me: !before.liked_by_me,
      like_count: before.like_count + (before.liked_by_me ? -1 : 1),
    }
    try {
      if (before.liked_by_me) await feedApi.unlikePost(before.id)
      else await feedApi.likePost(before.id)
    } catch {
      posts.value[index] = before // 静默回滚:点赞是点缀信息,不打断浏览
    }
  }

  async function removePost(id: number): Promise<void> {
    await feedApi.deletePost(id)
    posts.value = posts.value.filter((p) => p.id !== id)
    count.value = Math.max(0, count.value - 1)
  }

  function prepend(post: Post): void {
    posts.value = [post, ...posts.value]
    count.value += 1
  }

  async function create(text: string, images: File[]): Promise<Post> {
    const post = await feedApi.createPost(text, images)
    prepend(post)
    return post
  }

  return {
    posts, count, loading, loadingMore, error, hasMore,
    load, loadMine, toggleLike, removePost, prepend, create,
  }
})
```

- [ ] **Step 5:跑测试确认通过** → Run: `cd web && npm run test:run tests/unit/feed-store.spec.ts && npm run type-check`;Expected: 5 passed

- [ ] **Step 6:提交**

```bash
git add web/src/api web/src/stores web/tests/unit
git commit -m "feat(web): 广场 API 与 store(分页追加 + 点赞乐观更新)"
```

### Task 7.2:广场流页(列数自适应)

**Files:**
- Create: `web/src/features/square/SquarePage.vue`
- Test: `web/tests/component/square-page.spec.ts`

**Interfaces:**
- Consumes: `useFeedStore()`、`PostCard`(Task 7.3)、`AppEmpty` / `AppErrorView` / `AppSkeleton`。
- Produces:`SquarePage`(路由 `/home/square`):网格列数随窗口宽度自适应(spec §6.3),**列数由 CSS 承担**:

```css
/* 卡片宽 360–520px 之间自动决定列数:1920 → 3 列,1440 → 2 列,更窄 → 1 列 */
grid-template-columns: repeat(auto-fill, minmax(min(100%, 360px), var(--feed-card-max)));
justify-content: center;
```

> jsdom 不做真实排版,**列数只能靠目检/Playwright 验证**;组件测试只断言「渲染了几条动态」与四态。

- [ ] **Step 1:写失败的测试**

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import SquarePage from '@/features/square/SquarePage.vue'
import { server } from '../support/server'

const post = (id: number) => ({
  id, author: { user_id: 3, nickname: '小雨', avatar_url: null }, text: `第 ${id} 条`,
  images: [], like_count: 0, comment_count: 0, liked_by_me: false, created_at: '2026-10-01T10:00:00Z',
})

const page = (results: unknown[], overrides = {}) => ({ count: results.length, next: null, previous: null, results, ...overrides })

function mountPage() {
  return mount(SquarePage, {
    global: { plugins: [createPinia()], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
}

describe('SquarePage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('渲染动态网格', async () => {
    server.use(mswHttp.get('/api/v1/posts', () => HttpResponse.json(page([post(1), post(2)]))))
    const w = mountPage()
    await flushPromises()

    expect(w.findAll('.post-card')).toHaveLength(2)
    expect(w.find('.square__grid').exists()).toBe(true)
  })

  it('没有动态时展示空态', async () => {
    server.use(mswHttp.get('/api/v1/posts', () => HttpResponse.json(page([]))))
    const w = mountPage()
    await flushPromises()

    expect(w.find('.app-empty').exists()).toBe(true)
  })

  it('加载失败展示错误态,重试后恢复', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/posts', () => {
        calls += 1
        return calls === 1
          ? HttpResponse.json({ code: 50002, message: '服务器开小差了', request_id: 'r' }, { status: 500 })
          : HttpResponse.json(page([post(1)]))
      }),
    )
    const w = mountPage()
    await flushPromises()
    expect(w.find('.app-error').exists()).toBe(true)

    await w.find('.app-error button').trigger('click')
    await flushPromises()
    expect(w.findAll('.post-card')).toHaveLength(1)
  })

  it('还有下一页时展示「加载更多」', async () => {
    server.use(
      mswHttp.get('/api/v1/posts', () => HttpResponse.json(page([post(1)], { count: 2, next: 'x' }))),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.square__more').exists()).toBe(true)
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/component/square-page.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现**(PostCard 在 Task 7.3 创建;本步骤先按下面的 props 约定引用 `{ post }` + `@like` + `@delete`)

```vue
<script setup lang="ts">
import { computed, onMounted } from 'vue'
import AppButton from '@/components/AppButton.vue'
import AppEmpty from '@/components/AppEmpty.vue'
import AppErrorView from '@/components/AppErrorView.vue'
import AppSkeleton from '@/components/AppSkeleton.vue'
import { useSessionStore } from '@/stores/session'
import { useFeedStore } from '@/stores/feed'
import PostCard from './PostCard.vue'

const store = useFeedStore()
const session = useSessionStore()

const showEmpty = computed(() => !store.loading && !store.error && store.posts.length === 0)

onMounted(() => {
  store.load().catch(() => {})
})
</script>

<template>
  <section class="square">
    <header class="square__head">
      <h1 class="square__title">广场</h1>
      <RouterLink :to="{ name: 'post-compose' }">
        <AppButton>发动态</AppButton>
      </RouterLink>
    </header>

    <div v-if="store.loading" class="square__grid">
      <AppSkeleton v-for="n in 4" :key="n" height="280px" radius="var(--radius-card)" />
    </div>

    <AppErrorView
      v-else-if="store.error && store.posts.length === 0"
      :message="store.error"
      @retry="store.load(true)"
    />

    <AppEmpty
      v-else-if="showEmpty"
      emoji="🌟"
      title="广场还很安静"
      description="发第一条动态,让大家认识你"
    />

    <div v-else class="square__grid">
      <PostCard
        v-for="item in store.posts"
        :key="item.id"
        :post="item"
        :mine="item.author.user_id === session.userId"
        @like="store.toggleLike(item)"
        @delete="store.removePost(item.id)"
      />
    </div>

    <div v-if="store.hasMore" class="square__footer">
      <AppButton class="square__more" variant="ghost" :loading="store.loadingMore" @click="store.load()">
        加载更多
      </AppButton>
    </div>
  </section>
</template>

<style scoped>
.square {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  padding: var(--space-lg) var(--space-section-gap);
}
.square__head { display: flex; align-items: center; justify-content: space-between; }
.square__title { margin: 0; font-size: var(--text-display); font-weight: var(--weight-extrabold); }
.square__grid {
  display: grid;
  /* 列数随宽度自适应(spec §6.3):单卡 360–520px 之间 */
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 360px), var(--feed-card-max)));
  justify-content: center;
  gap: var(--space-card-gap);
}
.square__footer { display: flex; justify-content: center; }
</style>
```

- [ ] **Step 4:跑测试确认通过** → 先完成 Task 7.3 的 `PostCard.vue`,再回到本任务跑测试。Run: `cd web && npm run test:run tests/component/square-page.spec.ts`;Expected: 4 passed

- [ ] **Step 5:提交(与 Task 7.3 一起提交亦可,但不要跨组)**

```bash
git add web/src/features/square web/tests/component
git commit -m "feat(web): 广场流页(列数自适应 + 四态)"
```

### Task 7.3:动态卡片与点赞

**Files:**
- Create: `web/src/features/square/PostCard.vue`
- Test: `web/tests/component/post-card.spec.ts`

**Interfaces:**
- Consumes: `Post`(Task 7.1)、`AppAvatar`、`AppButton`。
- Produces:`PostCard.vue` —— props `{ post: Post; mine?: boolean }`;emits `like`、`delete`、`report`;图片按 1/2/3+ 三种网格排布;`mine` 时显示删除按钮。

- [ ] **Step 1:写失败的测试**

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PostCard from '@/features/square/PostCard.vue'

const base = {
  id: 1,
  author: { user_id: 3, nickname: '小雨', avatar_url: null },
  text: '今天天气不错',
  images: [],
  like_count: 2,
  comment_count: 1,
  liked_by_me: false,
  created_at: '2026-10-01T10:00:00Z',
}

function mountCard(overrides: Record<string, unknown> = {}, mine = false) {
  return mount(PostCard, {
    props: { post: { ...base, ...overrides } as never, mine },
    global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
}

describe('PostCard', () => {
  it('展示作者、正文、点赞与评论数', () => {
    const w = mountCard()
    expect(w.text()).toContain('小雨')
    expect(w.text()).toContain('今天天气不错')
    expect(w.find('.post-card__like').text()).toContain('2')
    expect(w.find('.post-card__comment').text()).toContain('1')
  })

  it('已点赞时按钮为选中态', () => {
    expect(mountCard({ liked_by_me: true }).find('.post-card__like').classes()).toContain('post-card__like--active')
  })

  it('点击点赞按钮派发 like 事件', async () => {
    const w = mountCard()
    await w.find('.post-card__like').trigger('click')
    expect(w.emitted('like')).toHaveLength(1)
  })

  it('图片数量决定网格类名', () => {
    expect(mountCard({ images: ['a'] }).find('.post-card__images--1').exists()).toBe(true)
    expect(mountCard({ images: ['a', 'b'] }).find('.post-card__images--2').exists()).toBe(true)
    expect(mountCard({ images: ['a', 'b', 'c'] }).find('.post-card__images--many').exists()).toBe(true)
  })

  it('是自己的动态才显示删除', async () => {
    expect(mountCard({}, true).find('.post-card__delete').exists()).toBe(true)
    expect(mountCard({}, false).find('.post-card__delete').exists()).toBe(false)
    const w = mountCard({}, true)
    await w.find('.post-card__delete').trigger('click')
    expect(w.emitted('delete')).toHaveLength(1)
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/component/post-card.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现**

```vue
<script setup lang="ts">
import { computed } from 'vue'
import AppAvatar from '@/components/AppAvatar.vue'
import type { Post } from '@/api/types'

const props = withDefaults(defineProps<{ post: Post; mine?: boolean }>(), { mine: false })
const emit = defineEmits<{ like: []; delete: []; report: [] }>()

const imagesClass = computed(() => {
  const n = props.post.images.length
  if (n === 1) return 'post-card__images--1'
  if (n === 2) return 'post-card__images--2'
  return 'post-card__images--many'
})

/** 列表里只显示到分钟,避免每张卡都带秒表。 */
const createdAtText = computed(() => {
  const date = new Date(props.post.created_at)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
})
</script>

<template>
  <article class="post-card">
    <header class="post-card__head">
      <RouterLink :to="{ name: 'user-profile', params: { id: props.post.author.user_id } }" class="post-card__author">
        <AppAvatar :src="props.post.author.avatar_url" :name="props.post.author.nickname" :size="36" />
        <span class="post-card__name">{{ props.post.author.nickname || '神秘人' }}</span>
      </RouterLink>
      <button v-if="props.mine" type="button" class="post-card__delete" @click="emit('delete')">删除</button>
    </header>

    <RouterLink :to="{ name: 'post-detail', params: { id: props.post.id } }" class="post-card__body">
      <p v-if="props.post.text" class="post-card__text">{{ props.post.text }}</p>
      <div v-if="props.post.images.length" class="post-card__images" :class="imagesClass">
        <img v-for="(url, i) in props.post.images" :key="i" :src="url" alt="" class="post-card__image" />
      </div>
    </RouterLink>

    <footer class="post-card__foot">
      <button
        type="button"
        class="post-card__like"
        :class="{ 'post-card__like--active': props.post.liked_by_me }"
        @click="emit('like')"
      >
        ♥ {{ props.post.like_count }}
      </button>
      <RouterLink :to="{ name: 'post-detail', params: { id: props.post.id } }" class="post-card__comment">
        💬 {{ props.post.comment_count }}
      </RouterLink>
      <span class="post-card__time">{{ createdAtText }}</span>
      <button type="button" class="post-card__report" @click="emit('report')">举报</button>
    </footer>
  </article>
</template>

<style scoped>
.post-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  padding: var(--space-lg);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-card);
  transition: box-shadow var(--motion-base) var(--ease-out);
}
.post-card:hover { box-shadow: var(--shadow-floating-bar); }
.post-card__head { display: flex; align-items: center; justify-content: space-between; }
.post-card__author { display: flex; align-items: center; gap: var(--space-sm); }
.post-card__name { font-weight: var(--weight-semibold); }
.post-card__delete, .post-card__report {
  border: none;
  background: none;
  color: var(--color-text2);
  font-size: var(--text-caption);
  cursor: pointer;
}
.post-card__delete:hover { color: var(--color-danger); }
.post-card__body { display: flex; flex-direction: column; gap: var(--space-md); }
.post-card__text { margin: 0; font-size: var(--text-body); white-space: pre-wrap; }
.post-card__images { display: grid; gap: var(--space-xs); }
.post-card__images--1 { grid-template-columns: 1fr; }
.post-card__images--2 { grid-template-columns: 1fr 1fr; }
.post-card__images--many { grid-template-columns: repeat(3, 1fr); }
.post-card__image {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  border-radius: var(--radius-image);
}
.post-card__images--1 .post-card__image { aspect-ratio: 4 / 3; }
.post-card__foot { display: flex; align-items: center; gap: var(--space-lg); font-size: var(--text-caption); }
.post-card__like, .post-card__comment {
  border: none;
  background: none;
  color: var(--color-text2);
  cursor: pointer;
  transition: color var(--motion-fast) var(--ease-out);
}
.post-card__like--active { color: var(--color-brand); }
.post-card__time { margin-left: auto; color: var(--color-text3); }
</style>
```

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿(含 Task 7.2 的用例)

- [ ] **Step 5:提交**

```bash
git add web/src/features/square web/tests/component
git commit -m "feat(web): 动态卡片与点赞"
```

### Task 7.4:发布动态

**Files:**
- Create: `web/src/features/square/PostComposePage.vue`
- Test: `web/tests/component/post-compose-page.spec.ts`

**Interfaces:**
- Consumes: `useFeedStore().create(text, images)`、`parseApiError`、`FormCard`。
- Produces:`PostComposePage`(路由 `/posts/compose`):正文 ≤500 字、图片 ≤9 张且单张 ≤5MB;正文与图片**至少填一个**;成功后回广场。

- [ ] **Step 1:写失败的测试**

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it } from 'vitest'
import PostComposePage from '@/features/square/PostComposePage.vue'
import { server } from '../support/server'

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div/>' } },
      { path: '/home/square', name: 'square', component: { template: '<div/>' } },
    ],
  })
  await router.push('/')
  await router.isReady()
  const w = mount(PostComposePage, { global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return { w, router }
}

describe('PostComposePage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('正文与图片都为空时不允许提交', async () => {
    const { w } = await mountPage()
    await w.find('.post-compose__submit').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('写点文字或选张图片吧')
  })

  it('提交成功跳回广场', async () => {
    server.use(
      mswHttp.post('/api/v1/posts', () =>
        HttpResponse.json({
          id: 9, author: { user_id: 3, nickname: '小雨', avatar_url: null }, text: 'hi',
          images: [], like_count: 0, comment_count: 0, liked_by_me: false, created_at: '2026-10-01T10:00:00Z',
        }),
      ),
    )
    const { w, router } = await mountPage()
    await w.find('textarea').setValue('hi')
    await w.find('.post-compose__submit').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/home/square')
  })

  it('单张超过 5MB 被前端拦下', async () => {
    const { w } = await mountPage()
    const big = new File([new Uint8Array(6 * 1024 * 1024)], 'big.jpg', { type: 'image/jpeg' })
    const input = w.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [big] })
    await input.trigger('change')
    await flushPromises()

    expect(w.text()).toContain('单张图片不能超过 5MB')
  })

  it('超过 9 张被前端拦下', async () => {
    const { w } = await mountPage()
    const files = Array.from({ length: 10 }, (_, i) => new File(['x'], `${i}.jpg`, { type: 'image/jpeg' }))
    const input = w.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: files })
    await input.trigger('change')
    await flushPromises()

    expect(w.text()).toContain('最多 9 张图片')
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/component/post-compose-page.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现**

```vue
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { parseApiError } from '@/api/error'
import AppButton from '@/components/AppButton.vue'
import FormCard from '@/features/auth/FormCard.vue'
import { useFeedStore } from '@/stores/feed'

const MAX_IMAGES = 9
const MAX_BYTES = 5 * 1024 * 1024

const router = useRouter()
const store = useFeedStore()

const text = ref('')
const images = ref<File[]>([])
const previews = ref<string[]>([])
const error = ref('')
const submitting = ref(false)

const canSubmit = computed(() => text.value.trim().length > 0 || images.value.length > 0)

function onPick(event: Event) {
  const input = event.target as HTMLInputElement
  const picked = Array.from(input.files ?? [])
  input.value = ''
  error.value = ''

  if (picked.some((f) => f.size > MAX_BYTES)) {
    error.value = '单张图片不能超过 5MB'
    return
  }
  const next = [...images.value, ...picked]
  if (next.length > MAX_IMAGES) {
    error.value = '最多 9 张图片'
    return
  }
  images.value = next
  previews.value = next.map((f) => URL.createObjectURL(f))
}

function removeImage(index: number) {
  const next = images.value.filter((_, i) => i !== index)
  images.value = next
  previews.value = next.map((f) => URL.createObjectURL(f))
}

async function onSubmit() {
  error.value = ''
  if (!canSubmit.value) {
    error.value = '写点文字或选张图片吧'
    return
  }
  submitting.value = true
  try {
    await store.create(text.value.trim(), images.value)
    await router.push({ name: 'square' })
  } catch (e) {
    error.value = parseApiError(e).message
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <FormCard title="发动态" description="正文最多 500 字,图片最多 9 张">
    <textarea
      v-model="text"
      class="post-compose__text"
      placeholder="此刻在想什么?"
      maxlength="500"
      rows="5"
    />
    <div class="post-compose__images">
      <figure v-for="(src, i) in previews" :key="src" class="post-compose__item">
        <img :src="src" alt="" class="post-compose__img" />
        <button type="button" class="post-compose__remove" @click="removeImage(i)">×</button>
      </figure>
      <label v-if="images.length < MAX_IMAGES" class="post-compose__add">
        <input type="file" accept="image/*" multiple class="post-compose__input" @change="onPick" />
        <span>+</span>
      </label>
    </div>
    <p v-if="error" class="post-compose__error">{{ error }}</p>
    <AppButton class="post-compose__submit" block size="lg" :loading="submitting" @click="onSubmit">
      发布
    </AppButton>
  </FormCard>
</template>

<style scoped>
.post-compose__text {
  width: 100%;
  padding: var(--space-md);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-input);
  font-family: var(--font-latin);
  font-size: var(--text-body);
  line-height: var(--leading-body);
  resize: vertical;
}
.post-compose__text:focus { border-color: var(--color-brand); outline: none; }
.post-compose__images { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-sm); }
.post-compose__item { position: relative; margin: 0; aspect-ratio: 1; }
.post-compose__img { width: 100%; height: 100%; object-fit: cover; border-radius: var(--radius-image); }
.post-compose__remove {
  position: absolute;
  top: var(--space-xs);
  right: var(--space-xs);
  width: 22px;
  height: 22px;
  border: none;
  border-radius: var(--radius-full);
  background: var(--color-photo-scrim);
  color: var(--color-bg-card);
  cursor: pointer;
}
.post-compose__add {
  display: flex;
  align-items: center;
  justify-content: center;
  aspect-ratio: 1;
  border: 1px dashed var(--color-text3);
  border-radius: var(--radius-image);
  color: var(--color-text3);
  font-size: var(--text-title);
  cursor: pointer;
}
.post-compose__input { display: none; }
.post-compose__error { margin: 0; font-size: var(--text-caption); color: var(--color-danger); }
</style>
```

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 5:提交**

```bash
git add web/src/features/square web/tests/component
git commit -m "feat(web): 发布动态(多图预览与前端拦截)"
```

### Task 7.5:动态详情与评论

**Files:**
- Create: `web/src/features/square/PostDetailPage.vue`、`web/src/features/square/CommentList.vue`
- Test: `web/tests/component/post-detail-page.spec.ts`

**Interfaces:**
- Consumes: `api/feed.ts` 的 `fetchPost` / `fetchComments` / `createComment`、`PostCard`、`AppInput`。
- Produces:`PostDetailPage`(路由 `/posts/:id`):详情 + 评论区(分页 + 发表);发表后插入列表并把 `comment_count` +1。

- [ ] **Step 1:写失败的测试**

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import PostDetailPage from '@/features/square/PostDetailPage.vue'
import { server } from '../support/server'

const post = {
  id: 5, author: { user_id: 3, nickname: '小雨', avatar_url: null }, text: '正文',
  images: [], like_count: 0, comment_count: 1, liked_by_me: false, created_at: '2026-10-01T10:00:00Z',
}
const comment = {
  id: 1, author: { user_id: 4, nickname: '阿哲', avatar_url: null }, text: '不错', created_at: '2026-10-01T11:00:00Z',
}
const paged = (results: unknown[]) => ({ count: results.length, next: null, previous: null, results })

function mountPage(id = '5') {
  return mount(PostDetailPage, {
    props: { id },
    global: { plugins: [createPinia()], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
}

describe('PostDetailPage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('渲染正文与评论', async () => {
    server.use(
      mswHttp.get('/api/v1/posts/5', () => HttpResponse.json(post)),
      mswHttp.get('/api/v1/posts/5/comments', () => HttpResponse.json(paged([comment]))),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.text()).toContain('正文')
    expect(w.text()).toContain('不错')
  })

  it('没有评论时展示空态', async () => {
    server.use(
      mswHttp.get('/api/v1/posts/5', () => HttpResponse.json(post)),
      mswHttp.get('/api/v1/posts/5/comments', () => HttpResponse.json(paged([]))),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.text()).toContain('还没有评论')
  })

  it('发表评论后出现在列表最前', async () => {
    server.use(
      mswHttp.get('/api/v1/posts/5', () => HttpResponse.json(post)),
      mswHttp.get('/api/v1/posts/5/comments', () => HttpResponse.json(paged([comment]))),
      mswHttp.post('/api/v1/posts/5/comments', () =>
        HttpResponse.json({ id: 2, author: { user_id: 9, nickname: '我', avatar_url: null }, text: '沙发', created_at: '2026-10-01T12:00:00Z' }),
      ),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('input[type="text"]').setValue('沙发')
    await w.find('.comment-list__submit').trigger('click')
    await flushPromises()

    expect(w.findAll('.comment-list__item')[0].text()).toContain('沙发')
  })

  it('动态 404 时展示提示,不重试', async () => {
    server.use(
      mswHttp.get('/api/v1/posts/5', () =>
        HttpResponse.json({ code: 40404, message: '动态不存在或不可见', request_id: 'r' }, { status: 404 }),
      ),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.text()).toContain('动态不存在或不可见')
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/component/post-detail-page.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现**

`CommentList.vue`:

```vue
<script setup lang="ts">
import { computed, ref } from 'vue'
import { parseApiError } from '@/api/error'
import AppAvatar from '@/components/AppAvatar.vue'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import * as feedApi from '@/api/feed'
import type { Comment } from '@/api/types'

const props = defineProps<{ postId: number; comments: Comment[]; count: number }>()
const emit = defineEmits<{ added: [Comment] }>()

const text = ref('')
const error = ref('')
const submitting = ref(false)
const offset = ref(props.comments.length)
const loadingMore = ref(false)

const hasMore = computed(() => props.comments.length < props.count)

async function onSubmit() {
  const value = text.value.trim()
  error.value = ''
  if (!value) {
    error.value = '评论不能为空'
    return
  }
  submitting.value = true
  try {
    const comment = await feedApi.createComment(props.postId, value)
    text.value = ''
    emit('added', comment)
  } catch (e) {
    error.value = parseApiError(e).message
  } finally {
    submitting.value = false
  }
}

async function loadMore() {
  loadingMore.value = true
  try {
    const page = await feedApi.fetchComments(props.postId, 20, offset.value)
    offset.value += page.results.length
    page.results.forEach((c) => emit('added', c))
  } finally {
    loadingMore.value = false
  }
}
</script>

<template>
  <section class="comment-list">
    <h2 class="comment-list__title">评论 {{ props.count }}</h2>

    <p v-if="props.comments.length === 0" class="comment-list__empty">还没有评论,来说两句</p>

    <ul class="comment-list__items">
      <li v-for="comment in props.comments" :key="comment.id" class="comment-list__item">
        <AppAvatar :src="comment.author.avatar_url" :name="comment.author.nickname" :size="32" />
        <div class="comment-list__body">
          <span class="comment-list__name">{{ comment.author.nickname || '神秘人' }}</span>
          <p class="comment-list__text">{{ comment.text }}</p>
        </div>
      </li>
    </ul>

    <AppButton v-if="hasMore" variant="ghost" block :loading="loadingMore" @click="loadMore">
      加载更多评论
    </AppButton>

    <div class="comment-list__form">
      <AppInput v-model="text" placeholder="说点什么…" :maxlength="200" :error="error" @enter="onSubmit" />
      <AppButton class="comment-list__submit" :loading="submitting" @click="onSubmit">发送</AppButton>
    </div>
  </section>
</template>

<style scoped>
.comment-list { display: flex; flex-direction: column; gap: var(--space-md); }
.comment-list__title { margin: 0; font-size: var(--text-subtitle); font-weight: var(--weight-semibold); }
.comment-list__empty { margin: 0; font-size: var(--text-caption); color: var(--color-text2); }
.comment-list__items { display: flex; flex-direction: column; gap: var(--space-md); margin: 0; padding: 0; list-style: none; }
.comment-list__item { display: flex; gap: var(--space-sm); }
.comment-list__body { display: flex; flex-direction: column; gap: var(--space-xs); }
.comment-list__name { font-size: var(--text-caption); color: var(--color-text2); }
.comment-list__text { margin: 0; font-size: var(--text-body); }
.comment-list__form { display: flex; align-items: flex-start; gap: var(--space-sm); }
.comment-list__form > :first-child { flex: 1; }
.comment-list__submit { flex: none; }
</style>
```

`PostDetailPage.vue`:

```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { parseApiError } from '@/api/error'
import * as feedApi from '@/api/feed'
import AppCard from '@/components/AppCard.vue'
import AppErrorView from '@/components/AppErrorView.vue'
import type { Comment, Post } from '@/api/types'
import CommentList from './CommentList.vue'
import PostCard from './PostCard.vue'

const props = defineProps<{ id: string }>()

const post = ref<Post | null>(null)
const comments = ref<Comment[]>([])
const error = ref('')
const fatal = ref(false) // 404:不可见,不给重试按钮

async function load() {
  error.value = ''
  fatal.value = false
  try {
    const postId = Number(props.id)
    post.value = await feedApi.fetchPost(postId)
    const page = await feedApi.fetchComments(postId)
    comments.value = page.results
  } catch (e) {
    const apiError = parseApiError(e)
    error.value = apiError.message
    fatal.value = apiError.status === 404
  }
}

onMounted(load)

function onCommentAdded(comment: Comment) {
  comments.value = [comment, ...comments.value]
  if (post.value) post.value.comment_count += 1
}
</script>

<template>
  <section class="post-detail">
    <AppCard v-if="post" padding="lg">
      <PostCard :post="post" @like="feedApi.likePost(post.id)" />
    </AppCard>

    <p v-if="error && fatal" class="post-detail__fatal">{{ error }}</p>
    <AppErrorView v-else-if="error" :message="error" @retry="load" />

    <AppCard v-if="post" padding="lg">
      <CommentList
        :post-id="Number(props.id)"
        :comments="comments"
        :count="post.comment_count"
        @added="onCommentAdded"
      />
    </AppCard>
  </section>
</template>

<style scoped>
.post-detail {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  max-width: clamp(560px, 56%, 760px);
  margin: 0 auto;
  padding: var(--space-section-gap) var(--space-page-h);
}
.post-detail__fatal { margin: 0; font-size: var(--text-body); color: var(--color-text2); text-align: center; }
</style>
```

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 5:提交**

```bash
git add web/src/features/square web/tests/component
git commit -m "feat(web): 动态详情与评论"
```

### Task 7.6:我的动态 / 删除 / 举报动态

**Files:**
- Modify: `web/src/features/square/MyPostsPage.vue`(替换空壳)
- Create: `web/src/features/moderation/ReportDialog.vue`(T8.3 复用,**本任务先建**)
- Test: `web/tests/component/report-dialog.spec.ts`

**Interfaces:**
- Consumes: `useFeedStore().loadMine()` / `removePost(id)`、`api/feed.ts` 的 `reportPost`、`AppButton`。
- Produces:
  - `ReportDialog.vue`:props `{ open: boolean; target: 'user' | 'post' }`;emits `close`、`submitted`;理由四选(`harassment` 骚扰 / `porn` 色情 / `fraud` 诈骗 / `other` 其他)+ 可选补充说明(≤200 字)
  - `MyPostsPage`(路由 `/my-posts`):我的动态列表 + 删除(二次确认)+ 举报

- [ ] **Step 1:写失败的测试**

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ReportDialog from '@/features/moderation/ReportDialog.vue'

describe('ReportDialog', () => {
  it('open 为 false 时不渲染', () => {
    expect(mount(ReportDialog, { props: { open: false, target: 'post' } }).find('.report-dialog').exists()).toBe(false)
  })

  it('未选理由时不能提交', async () => {
    const w = mount(ReportDialog, { props: { open: true, target: 'post' } })
    await w.find('.report-dialog__submit').trigger('click')
    expect(w.text()).toContain('请选择举报理由')
    expect(w.emitted('submitted')).toBeUndefined()
  })

  it('选择理由后派发 submitted 并带上类型', async () => {
    const w = mount(ReportDialog, { props: { open: true, target: 'post' } })
    await w.findAll('.report-dialog__reason')[1].trigger('click') // porn
    await w.find('.report-dialog__submit').trigger('click')

    expect(w.emitted('submitted')?.[0]).toEqual(['porn', ''])
  })

  it('可以填补充说明', async () => {
    const w = mount(ReportDialog, { props: { open: true, target: 'user' } })
    await w.findAll('.report-dialog__reason')[0].trigger('click')
    await w.find('textarea').setValue('一直发广告')
    await w.find('.report-dialog__submit').trigger('click')

    expect(w.emitted('submitted')?.[0]).toEqual(['harassment', '一直发广告'])
  })

  it('点取消派发 close', async () => {
    const w = mount(ReportDialog, { props: { open: true, target: 'user' } })
    await w.find('.report-dialog__cancel').trigger('click')
    expect(w.emitted('close')).toHaveLength(1)
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/component/report-dialog.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现 `ReportDialog.vue`**

```vue
<script setup lang="ts">
import { ref, watch } from 'vue'
import AppButton from '@/components/AppButton.vue'
import type { ReportType } from '@/api/types'

const props = defineProps<{ open: boolean; target: 'user' | 'post' }>()
const emit = defineEmits<{ close: []; submitted: [ReportType, string] }>()

/** 四类理由与后端枚举一一对应(moderation.md §4.1 / feed.md §5.10)。 */
const REASONS: { value: ReportType; label: string }[] = [
  { value: 'harassment', label: '骚扰' },
  { value: 'porn', label: '色情' },
  { value: 'fraud', label: '诈骗' },
  { value: 'other', label: '其他' },
]

const reason = ref<ReportType | ''>('')
const detail = ref('')
const error = ref('')

// 每次打开都从干净状态开始
watch(() => props.open, (open) => {
  if (open) {
    reason.value = ''
    detail.value = ''
    error.value = ''
  }
})

function onSubmit() {
  if (!reason.value) {
    error.value = '请选择举报理由'
    return
  }
  emit('submitted', reason.value, detail.value.trim())
}

function onClose() {
  emit('close')
}
</script>

<template>
  <div v-if="props.open" class="report-dialog" role="dialog" aria-modal="true">
    <div class="report-dialog__panel">
      <h2 class="report-dialog__title">举报{{ props.target === 'post' ? '动态' : '用户' }}</h2>
      <p class="report-dialog__desc">我们会尽快核实处理,你的举报是匿名的</p>

      <div class="report-dialog__reasons">
        <button
          v-for="item in REASONS"
          :key="item.value"
          type="button"
          class="report-dialog__reason"
          :class="{ 'report-dialog__reason--active': reason === item.value }"
          @click="reason = item.value"
        >
          {{ item.label }}
        </button>
      </div>

      <textarea
        v-model="detail"
        class="report-dialog__detail"
        placeholder="补充说明(选填,最多 200 字)"
        maxlength="200"
        rows="3"
      />
      <p v-if="error" class="report-dialog__error">{{ error }}</p>

      <div class="report-dialog__actions">
        <AppButton class="report-dialog__cancel" variant="ghost" block @click="onClose">取消</AppButton>
        <AppButton class="report-dialog__submit" block @click="onSubmit">提交举报</AppButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
.report-dialog {
  position: fixed;
  inset: 0;
  z-index: 85;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgb(22 24 29 / 55%);
}
.report-dialog__panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  width: var(--form-card-max);
  padding: var(--space-xxl);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-floating-bar);
}
.report-dialog__title { margin: 0; font-size: var(--text-title); font-weight: var(--weight-bold); }
.report-dialog__desc { margin: 0; font-size: var(--text-caption); color: var(--color-text2); }
.report-dialog__reasons { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-sm); }
.report-dialog__reason {
  height: 40px;
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-chip);
  background: var(--color-bg-card);
  cursor: pointer;
}
.report-dialog__reason--active { border-color: var(--color-brand); color: var(--color-brand); }
.report-dialog__detail {
  padding: var(--space-md);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-input);
  font-family: var(--font-latin);
  font-size: var(--text-body);
  resize: vertical;
}
.report-dialog__error { margin: 0; font-size: var(--text-caption); color: var(--color-danger); }
.report-dialog__actions { display: flex; gap: var(--space-md); }
</style>
```

- [ ] **Step 4:实现 `MyPostsPage.vue`(替换空壳)**

```vue
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { parseApiError } from '@/api/error'
import * as feedApi from '@/api/feed'
import AppEmpty from '@/components/AppEmpty.vue'
import AppErrorView from '@/components/AppErrorView.vue'
import type { Post, ReportType } from '@/api/types'
import { useFeedStore } from '@/stores/feed'
import PostCard from './PostCard.vue'
import ReportDialog from '@/features/moderation/ReportDialog.vue'

const store = useFeedStore()
const notice = ref('')
const reportTarget = ref<Post | null>(null)

const showEmpty = computed(() => !store.loading && !store.error && store.posts.length === 0)

onMounted(() => {
  store.loadMine(true).catch(() => {})
})

async function onDelete(post: Post) {
  if (!window.confirm('删除这条动态?删除后不可恢复')) return
  notice.value = ''
  try {
    await store.removePost(post.id)
  } catch (e) {
    notice.value = parseApiError(e).message
  }
}

async function onReport(type: ReportType, detail: string) {
  const target = reportTarget.value
  reportTarget.value = null
  if (!target) return
  try {
    await feedApi.reportPost(target.id, type, detail)
    notice.value = '已收到举报,我们会尽快核实'
  } catch (e) {
    notice.value = parseApiError(e).message
  }
}
</script>

<template>
  <section class="my-posts">
    <h1 class="my-posts__title">我的动态</h1>
    <p v-if="notice" class="my-posts__notice">{{ notice }}</p>

    <AppEmpty v-if="showEmpty" emoji="📝" title="还没发过动态" description="去广场发一条吧" />
    <AppErrorView v-else-if="store.error" :message="store.error" @retry="store.loadMine(true)" />

    <div v-else class="my-posts__grid">
      <PostCard
        v-for="item in store.posts"
        :key="item.id"
        :post="item"
        mine
        @like="store.toggleLike(item)"
        @delete="onDelete(item)"
        @report="reportTarget = item"
      />
    </div>

    <ReportDialog
      :open="reportTarget !== null"
      target="post"
      @close="reportTarget = null"
      @submitted="onReport"
    />
  </section>
</template>

<style scoped>
.my-posts { display: flex; flex-direction: column; gap: var(--space-lg); padding: var(--space-lg) var(--space-section-gap); }
.my-posts__title { margin: 0; font-size: var(--text-display); font-weight: var(--weight-extrabold); }
.my-posts__notice { margin: 0; font-size: var(--text-caption); color: var(--color-text2); }
.my-posts__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 360px), var(--feed-card-max)));
  justify-content: center;
  gap: var(--space-card-gap);
}
</style>
```

- [ ] **Step 5:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 6:提交**

```bash
git add web/src/features/square web/src/features/moderation web/tests/component
git commit -m "feat(web): 我的动态/删除,举报弹窗(用户与动态共用)"
```

**▶ 组 T7 检查点**:门禁全绿;真后端手测「发动态(带图)→ 广场看到 → 点赞 → 评论 → 删除」;目检窗口从 1920 拖到 1100 时**列数从 3 变 2 再变 1**。

---

## 组 T8:设置 / 拉黑 / 举报 / 在线状态(4 个任务)

### Task 8.1:设置页与退出登录

**Files:**
- Modify: `web/src/features/settings/SettingsPage.vue`(替换空壳)
- Test: `web/tests/component/settings-page.spec.ts`

**Interfaces:**
- Consumes: `useSessionStore().logout()`、`AppCard` / `AppButton`。
- Produces:`SettingsPage`(路由 `/settings`):入口(编辑资料 / 想找的人 / 黑名单 / 我的动态 / 协议)+ 退出登录(二次确认)。

> **退出顺序**:先 `im.logout()`(Task 6.2 提供)再 `session.logout()`。本任务先只做 `session.logout()`,并在代码里留 TODO 注释指向 Task 6.2 —— **这是计划内唯一允许的 TODO**,因为 IM 层在 T6 才存在。

- [ ] **Step 1:写失败的测试**

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsPage from '@/features/settings/SettingsPage.vue'
import { tokenStore } from '@/api/token-store'

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div/>' } },
      { path: '/login', name: 'login', component: { template: '<div/>' } },
    ],
  })
  await router.push('/')
  await router.isReady()
  const w = mount(SettingsPage, {
    global: { plugins: [createPinia(), router], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
  await flushPromises()
  return { w, router }
}

describe('SettingsPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('列出全部设置入口', async () => {
    const { w } = await mountPage()
    for (const label of ['编辑资料', '想找的人', '黑名单', '我的动态', '用户协议', '隐私政策']) {
      expect(w.text()).toContain(label)
    }
  })

  it('确认后退出登录:清凭证并跳登录页', async () => {
    tokenStore.access = 'a'
    tokenStore.refresh = 'r'
    tokenStore.userId = 9
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    const { w, router } = await mountPage()
    await w.find('.settings__logout').trigger('click')
    await flushPromises()

    expect(tokenStore.access).toBeNull()
    expect(router.currentRoute.value.path).toBe('/login')
  })

  it('取消则不退出', async () => {
    tokenStore.access = 'a'
    vi.spyOn(window, 'confirm').mockReturnValue(false)

    const { w } = await mountPage()
    await w.find('.settings__logout').trigger('click')
    await flushPromises()

    expect(tokenStore.access).toBe('a')
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/component/settings-page.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现**

```vue
<script setup lang="ts">
import { useRouter } from 'vue-router'
import AppButton from '@/components/AppButton.vue'
import AppCard from '@/components/AppCard.vue'
import { useSessionStore } from '@/stores/session'

const router = useRouter()
const session = useSessionStore()

const entries = [
  { name: 'profile-edit', label: '编辑资料' },
  { name: 'preference', label: '想找的人' },
  { name: 'settings-blocks', label: '黑名单' },
  { name: 'my-posts', label: '我的动态' },
  { name: 'legal-agreement', label: '用户协议' },
  { name: 'legal-privacy', label: '隐私政策' },
] as const

async function onLogout() {
  if (!window.confirm('确定退出登录?')) return
  // TODO(Task 6.2):IM 层就绪后,先 await im.logout() 再清会话
  session.logout()
  await router.push({ name: 'login' })
}
</script>

<template>
  <section class="settings">
    <h1 class="settings__title">设置</h1>

    <AppCard padding="lg">
      <ul class="settings__list">
        <li v-for="entry in entries" :key="entry.name">
          <RouterLink class="settings__item" :to="{ name: entry.name }">
            {{ entry.label }}
          </RouterLink>
        </li>
      </ul>
    </AppCard>

    <AppButton class="settings__logout" variant="danger" block size="lg" @click="onLogout">
      退出登录
    </AppButton>
  </section>
</template>

<style scoped>
.settings {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  max-width: clamp(480px, 48%, 640px);
  margin: 0 auto;
  padding: var(--space-section-gap) var(--space-page-h);
}
.settings__title { margin: 0; font-size: var(--text-display); font-weight: var(--weight-extrabold); }
.settings__list { display: flex; flex-direction: column; margin: 0; padding: 0; list-style: none; }
.settings__item {
  display: flex;
  align-items: center;
  height: 48px;
  border-bottom: 1px solid var(--color-divider);
  transition: color var(--motion-fast) var(--ease-out);
}
.settings__list li:last-child .settings__item { border-bottom: none; }
.settings__item:hover { color: var(--color-brand); }
</style>
```

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 5:提交**

```bash
git add web/src/features/settings web/tests/component
git commit -m "feat(web): 设置页与退出登录"
```

### Task 8.2:黑名单(分页 / 解除拉黑)

**Files:**
- Create: `web/src/api/moderation.ts`
- Modify: `web/src/stores/profile.ts`(追加黑名单状态)或新建 `web/src/stores/blocks.ts`
- Modify: `web/src/features/settings/BlockedUsersPage.vue`(替换空壳)
- Test: `web/tests/unit/blocks-store.spec.ts`

**Interfaces:**
- Consumes: `http`、`Page<T>`。
- Produces:

```ts
export interface BlockedUser {
  user_id: number
  nickname: string
  avatar_url: string | null
  blocked_at: string
}
```

- `api/moderation.ts`:`fetchBlocks(limit, offset)`、`blockUser(targetUserId)`、`unblockUser(userId)`、`reportUser(targetUserId, type, detail)`
- `useBlocksStore()`:state `blocks` / `count`;actions `load(reset)`、`unblock(userId)`、`block(targetUserId)`

- [ ] **Step 1:写失败的测试**

`web/tests/unit/blocks-store.spec.ts`:

```ts
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { useBlocksStore } from '@/stores/blocks'
import { server } from '../support/server'

const page = (results: unknown[]) => ({ count: results.length, next: null, previous: null, results })
const blocked = (id: number) => ({ user_id: id, nickname: `用户${id}`, avatar_url: null, blocked_at: '2026-10-01T00:00:00Z' })

describe('blocks store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('拉取黑名单', async () => {
    server.use(mswHttp.get('/api/v1/blocks', () => HttpResponse.json(page([blocked(1)]))))
    const store = useBlocksStore()

    await store.load(true)

    expect(store.blocks).toHaveLength(1)
    expect(store.count).toBe(1)
  })

  it('解除拉黑后从列表移除(幂等,删除不存在的也返回成功)', async () => {
    server.use(
      mswHttp.get('/api/v1/blocks', () => HttpResponse.json(page([blocked(1), blocked(2)]))),
      mswHttp.delete('/api/v1/blocks/1', () => new HttpResponse(null, { status: 204 })),
    )
    const store = useBlocksStore()
    await store.load(true)

    await store.unblock(1)

    expect(store.blocks.map((b) => b.user_id)).toEqual([2])
    expect(store.count).toBe(1)
  })

  it('拉黑某人后写入后端并可重新拉取', async () => {
    let created = false
    server.use(
      mswHttp.get('/api/v1/blocks', () => HttpResponse.json(page(created ? [blocked(5)] : []))),
      mswHttp.post('/api/v1/blocks', () => {
        created = true
        return new HttpResponse(null, { status: 201 })
      }),
    )
    const store = useBlocksStore()
    await store.load(true)

    await store.block(5)
    await store.load(true)

    expect(store.blocks.map((b) => b.user_id)).toEqual([5])
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/unit/blocks-store.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现 `api/moderation.ts`**

```ts
import { http } from './http'
import type { Page, ReportType } from './types'

export interface BlockedUser {
  user_id: number
  nickname: string
  avatar_url: string | null
  blocked_at: string
}

export async function fetchBlocks(limit = 20, offset = 0): Promise<Page<BlockedUser>> {
  const { data } = await http.get('/blocks', { params: { limit, offset } })
  return data as Page<BlockedUser>
}

export async function blockUser(targetUserId: number): Promise<void> {
  await http.post('/blocks', { target_user_id: targetUserId })
}

export async function unblockUser(userId: number): Promise<void> {
  await http.delete(`/blocks/${userId}`)
}

export async function reportUser(targetUserId: number, type: ReportType, detail = ''): Promise<void> {
  await http.post('/reports', { target_user_id: targetUserId, type, detail })
}
```

- [ ] **Step 4:实现 `stores/blocks.ts` 与页面**

`web/src/stores/blocks.ts`:

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as moderationApi from '@/api/moderation'
import type { BlockedUser } from '@/api/moderation'

const PAGE_SIZE = 20

export const useBlocksStore = defineStore('blocks', () => {
  const blocks = ref<BlockedUser[]>([])
  const count = ref(0)
  const offset = ref(0)

  async function load(reset = false): Promise<void> {
    if (reset) {
      blocks.value = []
      offset.value = 0
    }
    const page = await moderationApi.fetchBlocks(PAGE_SIZE, offset.value)
    blocks.value = [...blocks.value, ...page.results]
    count.value = page.count
    offset.value += page.results.length
  }

  async function unblock(userId: number): Promise<void> {
    await moderationApi.unblockUser(userId) // 幂等:解除不存在的拉黑也返回成功
    blocks.value = blocks.value.filter((b) => b.user_id !== userId)
    count.value = Math.max(0, count.value - 1)
  }

  async function block(targetUserId: number): Promise<void> {
    await moderationApi.blockUser(targetUserId)
  }

  return { blocks, count, load, unblock, block }
})
```

`BlockedUsersPage.vue`(替换空壳):列表 + 每条「解除」按钮 + 空态 + 「加载更多」。

- [ ] **Step 5:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 6:提交**

```bash
git add web/src/api web/src/stores web/src/features/settings web/tests/unit
git commit -m "feat(web): 黑名单分页与解除拉黑"
```

### Task 8.3:举报用户(接进用户资料页)

**Files:**
- Create: `web/src/features/profile/UserProfilePage.vue`(替换空壳)
- Test: `web/tests/component/user-profile-page.spec.ts`

**Interfaces:**
- Consumes: `api/users.ts` 的 `fetchUserProfile(userId)`、`ReportDialog`(Task 7.6)、`api/moderation.ts` 的 `reportUser` / `blockUser`。
- Produces:`UserProfilePage`(路由 `/users/:id`):对方公开资料 + 「举报」+「拉黑」两个操作;拉黑前二次确认;`404` 时不重试(对方已不可见)。

- [ ] **Step 1:写失败的测试**

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import UserProfilePage from '@/features/profile/UserProfilePage.vue'
import { server } from '../support/server'

const profile = {
  user_id: 8, nickname: '小雨', gender: 'female', age: 26, city: '上海', bio: '喜欢爬山',
  tags: [{ id: 1, name: '旅行', icon: 'plane' }],
  photos: [{ id: 1, url: 'https://cdn/a.jpg', status: 'approved', order: 0 }],
}

function mountPage(id = '8') {
  return mount(UserProfilePage, {
    props: { id },
    global: { plugins: [createPinia()], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
}

describe('UserProfilePage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('展示公开资料', async () => {
    server.use(mswHttp.get('/api/v1/users/8', () => HttpResponse.json(profile)))
    const w = mountPage()
    await flushPromises()

    expect(w.text()).toContain('小雨')
    expect(w.text()).toContain('喜欢爬山')
  })

  it('404(已拉黑/重封禁)展示不可见提示且不重试', async () => {
    server.use(
      mswHttp.get('/api/v1/users/8', () =>
        HttpResponse.json({ code: 40403, message: '用户不存在', request_id: 'r' }, { status: 404 }),
      ),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.text()).toContain('用户不存在')
    expect(w.find('.app-error button').exists()).toBe(false) // 不给重试
  })

  it('举报提交后展示受理提示', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      mswHttp.get('/api/v1/users/8', () => HttpResponse.json(profile)),
      mswHttp.post('/api/v1/reports', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 1, type: 'harassment', status: 'pending' })
      }),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('.user-profile__report').trigger('click')
    await flushPromises()
    await w.findAll('.report-dialog__reason')[0].trigger('click')
    await w.find('.report-dialog__submit').trigger('click')
    await flushPromises()

    expect(body).toMatchObject({ target_user_id: 8, type: 'harassment' })
    expect(w.text()).toContain('已收到举报')
  })

  it('拉黑需二次确认,确认后调用接口', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    let called = false
    server.use(
      mswHttp.get('/api/v1/users/8', () => HttpResponse.json(profile)),
      mswHttp.post('/api/v1/blocks', () => {
        called = true
        return new HttpResponse(null, { status: 201 })
      }),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('.user-profile__block').trigger('click')
    await flushPromises()

    expect(confirmSpy).toHaveBeenCalled()
    expect(called).toBe(true)
    expect(w.text()).toContain('已拉黑')
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/component/user-profile-page.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现**

```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { parseApiError } from '@/api/error'
import * as moderationApi from '@/api/moderation'
import * as usersApi from '@/api/users'
import AppAvatar from '@/components/AppAvatar.vue'
import AppButton from '@/components/AppButton.vue'
import AppCard from '@/components/AppCard.vue'
import ReportDialog from '@/features/moderation/ReportDialog.vue'
import type { PublicProfile, ReportType } from '@/api/types'

const props = defineProps<{ id: string }>()

const profile = ref<PublicProfile | null>(null)
const error = ref('')
const fatal = ref(false)
const notice = ref('')
const reporting = ref(false)

async function load() {
  error.value = ''
  fatal.value = false
  try {
    profile.value = await usersApi.fetchUserProfile(Number(props.id))
  } catch (e) {
    const apiError = parseApiError(e)
    error.value = apiError.message
    fatal.value = apiError.status === 404 // 双向拉黑/重封禁:不要重试(users.md §2.9)
  }
}

onMounted(load)

async function onReport(type: ReportType, detail: string) {
  reporting.value = false
  try {
    await moderationApi.reportUser(Number(props.id), type, detail)
    notice.value = '已收到举报,我们会尽快核实'
  } catch (e) {
    notice.value = parseApiError(e).message
  }
}

async function onBlock() {
  if (!window.confirm('拉黑后你们将互相看不到对方,确定吗?')) return
  notice.value = ''
  try {
    await moderationApi.blockUser(Number(props.id))
    notice.value = '已拉黑'
  } catch (e) {
    notice.value = parseApiError(e).message
  }
}
</script>

<template>
  <section class="user-profile">
    <AppCard v-if="profile" padding="lg">
      <div class="user-profile__head">
        <AppAvatar :src="profile.photos[0]?.url ?? null" :name="profile.nickname" :size="72" />
        <div>
          <h1 class="user-profile__name">{{ profile.nickname || '神秘人' }}</h1>
          <p class="user-profile__meta">
            {{ profile.age ? `${profile.age} 岁 · ` : '' }}{{ profile.city || '未填城市' }}
          </p>
        </div>
      </div>
      <p v-if="profile.bio" class="user-profile__bio">{{ profile.bio }}</p>
      <div v-if="profile.tags.length" class="user-profile__tags">
        <span v-for="tag in profile.tags" :key="tag.id" class="user-profile__tag">{{ tag.name }}</span>
      </div>
      <div class="user-profile__photos">
        <img v-for="photo in profile.photos" :key="photo.id" :src="photo.url" alt="" class="user-profile__photo" />
      </div>
      <div class="user-profile__actions">
        <AppButton class="user-profile__report" variant="ghost" @click="reporting = true">举报</AppButton>
        <AppButton class="user-profile__block" variant="danger" @click="onBlock">拉黑</AppButton>
      </div>
      <p v-if="notice" class="user-profile__notice">{{ notice }}</p>
    </AppCard>

    <p v-else-if="error && fatal" class="user-profile__fatal">{{ error }}</p>

    <ReportDialog :open="reporting" target="user" @close="reporting = false" @submitted="onReport" />
  </section>
</template>

<style scoped>
.user-profile {
  max-width: clamp(520px, 52%, 720px);
  margin: 0 auto;
  padding: var(--space-section-gap) var(--space-page-h);
}
.user-profile__head { display: flex; align-items: center; gap: var(--space-lg); }
.user-profile__name { margin: 0; font-size: var(--text-title); font-weight: var(--weight-bold); }
.user-profile__meta { margin: 0; font-size: var(--text-caption); color: var(--color-text2); }
.user-profile__bio { margin: var(--space-md) 0 0; font-size: var(--text-body); }
.user-profile__tags { display: flex; flex-wrap: wrap; gap: var(--space-sm); margin-top: var(--space-md); }
.user-profile__tag {
  padding: 2px var(--space-md);
  border-radius: var(--radius-full);
  background: var(--color-bg-page);
  font-size: var(--text-caption);
}
.user-profile__photos { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-sm); margin-top: var(--space-lg); }
.user-profile__photo { width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: var(--radius-image); }
.user-profile__actions { display: flex; gap: var(--space-md); margin-top: var(--space-lg); }
.user-profile__notice { margin: var(--space-md) 0 0; font-size: var(--text-caption); color: var(--color-text2); }
.user-profile__fatal { margin: 0; text-align: center; color: var(--color-text2); }
</style>
```

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 5:提交**

```bash
git add web/src/features/profile web/tests/component
git commit -m "feat(web): 他人资料页(举报 / 拉黑)"
```

### Task 8.4:在线状态(轮询即心跳)

**Files:**
- Create: `web/src/stores/presence.ts`
- Modify: `web/src/features/discovery/CandidateCard.vue`(接线 `online`)、`web/src/features/chat/ChatsPage.vue`(T6 用)、`web/src/features/profile/UserProfilePage.vue`(在线光)
- Test: `web/tests/unit/presence-store.spec.ts`

**Interfaces:**
- Consumes: `http`、`HEARTBEAT_INTERVAL_MS`(计划一 Task 1.1 定义的 45 秒常量)。
- Produces:

```ts
export interface PresenceItem { user_id: number; online: boolean; last_active_at: string | null }
```

- `usePresenceStore()`:state `online: Map<number, boolean>`;actions `track(owner: string, ids: number[])`、`refresh()`、`isOnline(userId: number): boolean`、`start()` / `stop()`
- **机制与 App 完全一致**(已核对 `app/lib/features/presence/presence_controller.dart`):
  1. **没有单独的「心跳接口」** —— 45 秒的 `GET /presence` 轮询本身就是心跳(后端口径是「120 秒内有认证请求即在线」)
  2. 多个页面各自 `track(owner, ids)`,合并去重后**一轮只发一次**请求
  3. 后端单次上限 100(`presence.py::PRESENCE_MAX_IDS`),超过按 100 分片
  4. **Web 差异(spec §8)**:`document.hidden` 时停止轮询,重新可见时**立即补一次**

> 与计划一的差异说明:计划一 T8.4 曾写 `useHeartbeat.ts` + `stores/presence.ts` 两个文件;实际把轮询与数据都收进 `stores/presence.ts` 一个文件更直(轮询本身就是心跳,拆开只是多一层转发)。计划一的 T8.4 行以本条为准。

- [ ] **Step 1:写失败的测试**

```ts
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePresenceStore } from '@/stores/presence'
import { server } from '../support/server'

describe('presence store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
  })
  afterEach(() => vi.useRealTimers())

  it('track 后拉取在线状态', async () => {
    server.use(
      mswHttp.get('/api/v1/presence', () =>
        HttpResponse.json({ results: [{ user_id: 8, online: true, last_active_at: null }] }),
      ),
    )
    const store = usePresenceStore()

    store.track('candidates', [8])
    await vi.runOnlyPendingTimersAsync()

    expect(store.isOnline(8)).toBe(true)
  })

  it('多个 owner 的 id 合并去重后只发一次请求', async () => {
    let calls = 0
    let seenIds = ''
    server.use(
      mswHttp.get('/api/v1/presence', ({ request }) => {
        calls += 1
        seenIds = new URL(request.url).searchParams.get('user_ids') ?? ''
        return HttpResponse.json({ results: [] })
      }),
    )
    const store = usePresenceStore()

    store.track('candidates', [8])
    store.track('chats', [8, 9])
    await vi.runOnlyPendingTimersAsync()

    expect(calls).toBe(1)
    expect(seenIds).toBe('8,9')
  })

  it('超过 100 个 id 时按 100 分片', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/presence', () => {
        calls += 1
        return HttpResponse.json({ results: [] })
      }),
    )
    const store = usePresenceStore()

    store.track('feed', Array.from({ length: 150 }, (_, i) => i + 1))
    await vi.runOnlyPendingTimersAsync()

    expect(calls).toBe(2)
  })

  it('45 秒后自动再拉一轮', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/presence', () => {
        calls += 1
        return HttpResponse.json({ results: [] })
      }),
    )
    const store = usePresenceStore()
    store.track('candidates', [8])
    await vi.runOnlyPendingTimersAsync()

    await vi.advanceTimersByTimeAsync(45_000)

    expect(calls).toBe(2)
  })

  it('页面隐藏时停止轮询,重新可见立刻补一次', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/presence', () => {
        calls += 1
        return HttpResponse.json({ results: [] })
      }),
    )
    const store = usePresenceStore()
    store.track('candidates', [8])
    await vi.runOnlyPendingTimersAsync()
    expect(calls).toBe(1)

    Object.defineProperty(document, 'hidden', { configurable: true, value: true })
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(120_000)
    expect(calls).toBe(1) // 隐藏期间不轮询

    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.runOnlyPendingTimersAsync()
    expect(calls).toBe(2) // 重新可见立即补一次
  })

  it('拉取失败保持旧值,不抛错', async () => {
    server.use(
      mswHttp.get('/api/v1/presence', () =>
        HttpResponse.json({ code: 50002, message: '服务器开小差了', request_id: 'r' }, { status: 500 }),
      ),
    )
    const store = usePresenceStore()
    store.track('candidates', [8])

    await expect(vi.runOnlyPendingTimersAsync()).resolves.toBeUndefined()
    expect(store.isOnline(8)).toBe(false)
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/unit/presence-store.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现**

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { http } from '@/api/http'
import { HEARTBEAT_INTERVAL_MS } from '@/constants'

/** 后端单次查询上限(chatapp/users/presence.py::PRESENCE_MAX_IDS)。 */
const BATCH_SIZE = 100

export const usePresenceStore = defineStore('presence', () => {
  const online = ref<Map<number, boolean>>(new Map())
  const owners = new Map<string, number[]>()
  let timer: number | undefined
  let scheduled = false

  /** 各页面登记自己关心的人;同一轮合并去重后只发一次请求。 */
  function track(owner: string, ids: number[]): void {
    const current = owners.get(owner)
    if (current && current.length === ids.length && ids.every((id) => current.includes(id))) return
    owners.set(owner, [...ids])
    startTimer()
    scheduleFetch()
  }

  function scheduleFetch(): void {
    if (scheduled) return
    scheduled = true
    queueMicrotask(async () => {
      scheduled = false
      await refresh()
    })
  }

  async function refresh(): Promise<void> {
    if (document.hidden) return // 页面不可见时不轮询(在线状态要如实反映是否在看)
    const ids = [...new Set([...owners.values()].flat())]
    if (ids.length === 0) return
    try {
      const next = new Map(online.value)
      for (let start = 0; start < ids.length; start += BATCH_SIZE) {
        const chunk = ids.slice(start, start + BATCH_SIZE)
        const { data } = await http.get('/presence', { params: { user_ids: chunk.join(',') } })
        for (const item of data.results as { user_id: number; online: boolean }[]) {
          next.set(item.user_id, item.online)
        }
      }
      online.value = next
    } catch {
      // 网络抖动:保留旧值,下个周期再试(点缀信息,不打扰用户)
    }
  }

  function startTimer(): void {
    if (timer !== undefined) return
    timer = window.setInterval(() => {
      void refresh()
    }, HEARTBEAT_INTERVAL_MS)
  }

  function stop(): void {
    if (timer !== undefined) window.clearInterval(timer)
    timer = undefined
  }

  function onVisibilityChange(): void {
    if (document.hidden) stop()
    else {
      startTimer()
      void refresh() // 重新可见立即补一次
    }
  }

  document.addEventListener('visibilitychange', onVisibilityChange)

  function isOnline(userId: number): boolean {
    return online.value.get(userId) ?? false
  }

  return { online, track, refresh, isOnline, stop }
})
```

- [ ] **Step 4:接线到卡片与资料页**

- `CandidateCard`:把 `online` 传进去(`<CandidateCard :candidate="store.current" :online="presence.isOnline(store.current.user_id)" />`),并在 `DiscoveryPage` 里 `presence.track('candidates', [store.current?.user_id].filter(Boolean))`
- `UserProfilePage`:资料卡右上角同样加在线光
- `ChatsPage`(T6)在会话行上接线

- [ ] **Step 5:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 6:提交**

```bash
git add web/src/stores web/src/features web/tests/unit
git commit -m "feat(web): 在线状态(轮询即心跳,隐藏时暂停)"
```

**▶ 组 T8 检查点**:门禁全绿;真后端手测「拉黑 → 黑名单里看到 → 解除」;开两个浏览器窗口用不同账号,复核在线光会亮。

---

## 执行记录

> 执行时在此追加实际偏差。

### T4 引导与资料(2026-10-05,分支 `feat/web-frontend`)

**计划自身的疏漏(执行时修正)**

1. **`load()` 抛不抛异常,计划自相矛盾**:4.1 的 store 实现既写 `error` 又 `rethrow`,而同一任务自带的用例是 `await store.load()`(没有 catch)→ 用例必红。定为「**错误只进 state,不抛**」,调用方读 `store.error`/`profile===null` 决定渲染;`save/uploadPhoto/...` 仍抛(页面要 catch 后展示后端文案)。守卫里的 `load().catch(()=>{})` 随之简化。
2. **组件测试的 pinia 用错**:4.1 自己写明「本任务起所有组件测试都用 `freshPinia()`」,但 4.3/4.4 的示例仍写 `plugins: [createPinia()]` —— 那会新建一个与预置状态无关的 pinia,组件读到空 store(4.3 首条用例必红)。全部改为 `freshPinia()` 并在同一实例上预置 + 挂载。
3. **multipart 用例断言了环境产物**:计划断言 `receivedName === 'me.jpg'`。实测必红,根因不是我们的代码 —— MSW 用 undici 序列化 FormData,而 undici 用 `instanceof File`(Node 的 File)取文件名,jsdom 的 `File` 不是同一个类 → 回落成 `filename="blob"`。**真浏览器已抓包复核**:请求体含 `Content-Disposition: form-data; name="file"; filename="me.jpg"`,后端 201 存为 `media/photos/2026/10/me.jpg`。用例改为只断言我们控制的契约(multipart、字段名 `file`、字节送达),并把这段原因写进注释,避免后人误判「上传文件名坏了」。
4. **页面 CSS 里的裸色值**:计划 4.6 用了 `rgb(255 44 85 / 8%)`(另有 T5/T7/T8 共 4 处同类)→ 按 token 纪律提为 Web 专属变量 `--tint-brand` / `--glow-online` / `--overlay-on-photo` / `--scrim-strong`(无 Dart 对照,放在「Web 新增维度」区;token 对账测试只从 Dart 侧正向要求,新增变量不影响)。
5. **`MyProfilePage` 的定宽写法**:计划用 `max-width: clamp(560px,56%,760px)`,在窄容器里会被内容撑开 → 改 `width: clamp(...)` + `max-width: 100%`,符合「宽度跟窗口自适应」的既定要求。

**真环境检查点(T4)**:门禁全绿(33 文件 / 146 用例 · `vue-tsc` 0 · `eslint` 0)。真后端手测通过:登录(新号,开发码 `123456`)→ 编辑资料填昵称/性别/生日/城市/简介 + 勾 2 个标签 → 「已保存」→ 上传真 JPEG → 我的页显示完整资料与照片「已通过」徽标;`GET /users/me` 复核为 `status:"complete"`、`tags:["旅行","咖啡"]`、`photos:1`,`GET /users/me/preference` 复核为 `{target_gender:"male",age_min:24,age_max:34,city:"上海"}`(不限/数值/城市三条契约都对)。




