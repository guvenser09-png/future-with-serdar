-- === Future with Serdar — Supabase Şeması (CLAUDE.md) ===
-- Supabase SQL Editor'a yapıştırıp çalıştırın.

create table if not exists news_items (
    id               bigint generated always as identity primary key,
    source           text        not null,
    url              text        not null,
    title            text        not null,
    summary          text,
    importance_score int,
    score_reasoning  text,
    used_in_episode  bigint,                 -- episodes.id (FK gevşek tutuldu)
    collected_at     timestamptz not null default now(),
    unique (url)
);

create index if not exists news_items_collected_at_idx on news_items (collected_at desc);
create index if not exists news_items_used_idx on news_items (used_in_episode);

create table if not exists episodes (
    id               bigint generated always as identity primary key,
    episode_number   int unique,
    date             date,
    title            text,
    description      text,
    duration_sec     int,
    mp3_url          text,
    mp3_bytes        bigint,
    youtube_video_id text,
    youtube_short_id text,
    status           text default 'draft',   -- draft | published | failed
    created_at       timestamptz not null default now()
);

create table if not exists pipeline_logs (
    id            bigint generated always as identity primary key,
    run_date      date,
    step          text,
    status        text,                       -- ok | error | skipped
    error_message text,
    duration_sec  numeric,
    created_at    timestamptz not null default now()
);

-- Faz 4
create table if not exists metrics (
    id          bigint generated always as identity primary key,
    episode_id  bigint references episodes(id),
    platform    text,                          -- spotify | youtube | apple
    plays       int,
    likes       int,
    captured_at timestamptz not null default now()
);
