-- Supabase SQL Editor'da bir kez çalıştırın.

create table if not exists public.konserler (
    id              text primary key,          -- sha1(sanatci_norm | tarih | sehir)
    sanatci         text not null,
    sanatci_norm    text not null,
    tarih           date not null,
    saat            text,
    sehir           text,
    mekan           text,
    min_fiyat       numeric(10,2),
    max_fiyat       numeric(10,2),
    kaynak_sayisi   int not null default 1,
    kaynaklar       text[] not null default '{}',
    ilk_gorulme     timestamptz not null default now(),
    son_guncelleme  timestamptz not null default now()
);

create table if not exists public.konser_ilanlari (
    id              text primary key,          -- sha1(kaynak | link)
    konser_id       text not null references public.konserler(id) on delete cascade,
    kaynak          text not null check (kaynak in ('bubilet', 'biletix', 'passo')),
    baslik          text not null,
    mekan           text,
    sehir           text,
    tarih           date not null,
    saat            text,
    fiyat           numeric(10,2),             -- Biletix listesinde fiyat yok, null kalır
    link            text,
    kaynak_id       text,
    cekilme_zamani  timestamptz,
    ilk_gorulme     timestamptz not null default now(),
    son_guncelleme  timestamptz not null default now()
);

create index if not exists konserler_tarih_idx   on public.konserler (tarih);
create index if not exists konserler_sanatci_idx on public.konserler (sanatci_norm);
create index if not exists ilanlar_konser_idx    on public.konser_ilanlari (konser_id);

-- Siteler arası fiyat kıyaslaması: her konser için site başına en düşük fiyat.
create or replace view public.fiyat_karsilastirma as
select
    k.id as konser_id, k.sanatci, k.tarih, k.sehir, k.mekan,
    min(i.fiyat) filter (where i.kaynak = 'bubilet') as bubilet_fiyat,
    min(i.fiyat) filter (where i.kaynak = 'biletix') as biletix_fiyat,
    min(i.fiyat) filter (where i.kaynak = 'passo')   as passo_fiyat,
    min(i.fiyat) as en_ucuz,
    k.kaynak_sayisi
from public.konserler k
join public.konser_ilanlari i on i.konser_id = k.id
where k.tarih >= current_date
group by k.id;

-- Okuma herkese açık (ileride yapılacak web arayüzü anon key ile okuyabilsin),
-- yazma sadece service_role ile (RLS'i service_role zaten bypass eder).
alter table public.konserler       enable row level security;
alter table public.konser_ilanlari enable row level security;

drop policy if exists "herkes okuyabilir" on public.konserler;
create policy "herkes okuyabilir" on public.konserler for select using (true);
drop policy if exists "herkes okuyabilir" on public.konser_ilanlari;
create policy "herkes okuyabilir" on public.konser_ilanlari for select using (true);

alter view public.fiyat_karsilastirma set (security_invoker = true);
