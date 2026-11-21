import { useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { useNearby } from '../api/queries'
import type { RestaurantCard, SortBy } from '../api/types'
import { LocationPicker } from '../components/LocationPicker'
import { CartBar, ErrorBox, Loading, RatingBadge } from '../components/ui'
import { useLocationPlace } from '../location/location'
import { rupees } from '../lib/money'
import { Arch, Drawing, RegionStrip, RegionWash } from '../theme/Art'
import { drawingFor, photoFor, SIGNATURE } from '../theme/dishes'
import { FILTER_REGIONS, REGIONS, regionFor, type Region } from '../theme/regions'

const CRAVINGS = ['Thali', 'Dosa', 'Momos', 'Dal Baati', 'Dhokla', 'Biryani']


export function HomePage() {
  const { place } = useLocationPlace()
  const [sort, setSort] = useState<SortBy>('distance')
  const [region, setRegion] = useState<Region | 'all'>('all')
  const near = useNearby(place.lat, place.lng, sort)
  const navigate = useNavigate()

  const cards = useMemo(() => {
    const all = (near.data?.restaurants ?? []).map((r) => ({ ...r, region: regionFor(r.cuisines) }))
    return region === 'all' ? all : all.filter((r) => r.region === region)
  }, [near.data, region])

  function onSearch(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const q = new FormData(e.currentTarget).get('q')?.toString().trim()
    if (q) navigate(`/search?q=${encodeURIComponent(q)}`)
  }

  return (
    <div className="page home">
      <header className="royal-header">
        <Drawing id="i-thali" size={150} />
        <Arch />
        <div className="brand">
          <span className="brand-name">QuickServe</span>
          <span className="brand-sub" lang="hi">
            शाही रसोई
          </span>
        </div>
        <LocationPicker />
      </header>
      <RegionStrip region="plain" />

      <main className="stack">
        <form role="search" className="search-box" onSubmit={onSearch}>
          <label htmlFor="home-q" className="visually-hidden">
            Search dishes or restaurants
          </label>
          <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#6E1423" strokeWidth="2" strokeLinecap="round">
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-3.5-3.5" />
          </svg>
          <input id="home-q" name="q" type="search" placeholder="Search dal baati, dosa, momos…" autoComplete="off" />
        </form>

        <section className="hero" aria-labelledby="hero-title">
          <RegionWash region="north" strength={0.22} />
          <div className="hero-text">
            <span className="eyebrow">Shahi Thali Utsav</span>
            <h2 id="hero-title">Royal thalis from five regions</h2>
            <Link to="/search?q=thali" className="btn light">
              Explore thalis
            </Link>
          </div>
          <div className="hero-plate">
            <HeroDish name="Punjabi Thali" />
          </div>
        </section>

        <section aria-labelledby="crave">
          <h2 id="crave" className="section-title">
            Craving something?
          </h2>
          <div className="cravings">
            {CRAVINGS.map((c) => (
              <Link key={c} to={`/search?q=${encodeURIComponent(c)}`} className="craving">
                <span className="craving-circle">
                  <HeroDish name={c} small />
                </span>
                {c}
              </Link>
            ))}
          </div>
        </section>

        <div role="group" aria-label="Filter by region" className="chips">
          {(['all', ...FILTER_REGIONS] as const).map((r) => (
            <button key={r} type="button" className="chip" aria-pressed={region === r} onClick={() => setRegion(r)}>
              {r === 'all' ? 'All' : REGIONS[r].label}
            </button>
          ))}
        </div>

        <div className="list-head">
          <h2 className="section-title" aria-live="polite">
            {near.isSuccess ? `${cards.length} restaurant${cards.length === 1 ? '' : 's'} near you` : 'Restaurants near you'}
          </h2>
          <label className="sort">
            <span className="visually-hidden">Sort by</span>
            <select value={sort} onChange={(e) => setSort(e.target.value as SortBy)}>
              <option value="distance">Nearest</option>
              <option value="rating">Top rated</option>
              <option value="eta">Fastest</option>
            </select>
          </label>
        </div>

        {near.isPending && <Loading label="Finding restaurants near you" />}
        {near.isError && <ErrorBox error={near.error} onRetry={() => near.refetch()} />}
        {near.isSuccess && cards.length === 0 && (
          <p className="empty">
            {region === 'all'
              ? 'No restaurant delivers here yet. Try another area from "Deliver to".'
              : `No ${REGIONS[region].label} restaurant delivers here yet.`}
          </p>
        )}
        <ul className="cards" aria-busy={near.isFetching}>
          {cards.map((r) => (
            <li key={r.id}>
              <RestaurantCardView card={r} region={r.region} dish={SIGNATURE[r.region]} />
            </li>
          ))}
        </ul>
        <p className="footnote">Only restaurants that deliver to you are shown.</p>
      </main>
      <CartBar />
    </div>
  )
}

function HeroDish({ name, small }: { name: string; small?: boolean }) {
  const photo = photoFor(name)
  if (photo) return <img src={photo} alt="" className={small ? 'round-photo small' : 'round-photo'} />
  return <Drawing id={drawingFor(name)} size={small ? 60 : 150} />
}

function RestaurantCardView({ card, region, dish }: { card: RestaurantCard; region: Region; dish: string }) {
  const photo = photoFor(dish)
  return (
    <Link to={`/r/${card.id}`} className="card" state={{ card }}>
      <div className="card-picture">
        {photo ? (
          <img src={photo} alt="" loading="lazy" decoding="async" />
        ) : (
          <>
            <RegionWash region={region} />
            <Drawing id={drawingFor(dish)} size={112} />
          </>
        )}
        {card.free_delivery_above && <span className="tag maroon">Free delivery above {rupees(card.free_delivery_above)}</span>}
        <span className="tag eta">{card.eta_text}</span>
      </div>
      <RegionStrip region={region} />
      <div className="card-body">
        <div className="card-title">
          <h3>{card.name}</h3>
          <RatingBadge rating={card.rating} count={card.rating_count} />
        </div>
        <p className="muted">{card.cuisines.join(', ') || 'Restaurant'}</p>
        <p>
          {card.distance_km} km · {rupees(card.delivery_fee)} delivery
          {card.rating_count > 0 && ` · ${card.rating_count} review${card.rating_count === 1 ? '' : 's'}`}
        </p>
      </div>
    </Link>
  )
}
