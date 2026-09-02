-- ============================================================================
-- 記帳功能的資料表（在 Supabase 的 SQL Editor 貼上執行一次即可）
--
-- 兩張表：
--   expenses        每一筆支出。前端登入後直接讀寫（RLS 隔離），
--                   iOS 捷徑的 Apple Pay 自動記帳走 /api/expense 寫入。
--   expense_tokens  自動記帳的 ingest token。前端登入後自己產生與撤銷；
--                   /api/expense 用 service role key 查 token → user_id。
--
-- 安全模型與自選清單（watchlists）相同：anon key 公開、隔離靠 RLS。
-- service role key 只放在 Vercel 環境變數（SUPABASE_SERVICE_ROLE_KEY），
-- 永遠不進前端、不進版控。
-- ============================================================================

create table if not exists public.expenses (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users (id) on delete cascade,
  amount     numeric not null check (amount > 0),
  currency   text not null default 'TWD',
  merchant   text not null default '',
  category   text not null default '未分類',
  note       text not null default '',
  source     text not null default 'manual' check (source in ('manual', 'applepay')),
  spent_at   timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create index if not exists expenses_user_spent_idx
  on public.expenses (user_id, spent_at desc);

alter table public.expenses enable row level security;

drop policy if exists "expenses select own" on public.expenses;
create policy "expenses select own" on public.expenses
  for select using (auth.uid() = user_id);

drop policy if exists "expenses insert own" on public.expenses;
create policy "expenses insert own" on public.expenses
  for insert with check (auth.uid() = user_id);

drop policy if exists "expenses update own" on public.expenses;
create policy "expenses update own" on public.expenses
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "expenses delete own" on public.expenses;
create policy "expenses delete own" on public.expenses
  for delete using (auth.uid() = user_id);

-- ----------------------------------------------------------------------------

create table if not exists public.expense_tokens (
  token      text primary key,
  user_id    uuid not null references auth.users (id) on delete cascade,
  label      text not null default 'iOS 捷徑',
  created_at timestamptz not null default now()
);

alter table public.expense_tokens enable row level security;

drop policy if exists "tokens select own" on public.expense_tokens;
create policy "tokens select own" on public.expense_tokens
  for select using (auth.uid() = user_id);

drop policy if exists "tokens insert own" on public.expense_tokens;
create policy "tokens insert own" on public.expense_tokens
  for insert with check (auth.uid() = user_id);

drop policy if exists "tokens delete own" on public.expense_tokens;
create policy "tokens delete own" on public.expense_tokens
  for delete using (auth.uid() = user_id);
