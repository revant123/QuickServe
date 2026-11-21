import { Drawing, RegionWash } from '../theme/Art'
import { drawingFor, photoFor } from '../theme/dishes'
import type { Region } from '../theme/regions'

/** A dish's photo if one was added, otherwise its drawing on the restaurant's regional pattern. */
export function DishPicture({ name, region, size }: { name: string; region: Region; size: number }) {
  const photo = photoFor(name)
  return (
    <div className="dish-picture" style={{ width: size, height: size }}>
      {photo ? (
        <img src={photo} alt={name} width={size} height={size} loading="lazy" decoding="async" />
      ) : (
        <>
          <RegionWash region={region} />
          <Drawing id={drawingFor(name)} size={Math.round(size * 0.86)} label={name} />
        </>
      )}
    </div>
  )
}
