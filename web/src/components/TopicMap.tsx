import 'leaflet/dist/leaflet.css'
import { CircleMarker, MapContainer, TileLayer, Tooltip } from 'react-leaflet'
import type { MapPoint } from '../api/types'

/** Places for the topic (orange) and its related topics, on OpenStreetMap tiles. */
export function TopicMap({ points }: { points: MapPoint[] }) {
  if (!points.length) return <p className="muted">No places for this topic.</p>
  const lats = points.map((p) => p.lat)
  const lons = points.map((p) => p.lon)
  const bounds: [[number, number], [number, number]] = [
    [Math.min(...lats) - 1, Math.min(...lons) - 1],
    [Math.max(...lats) + 1, Math.max(...lons) + 1],
  ]
  return (
    <MapContainer className="map" bounds={bounds} scrollWheelZoom={false}>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {points.map((p, i) => (
        <CircleMarker key={`${p.id}-${i}`} center={[p.lat, p.lon]} radius={p.role === 'topic' ? 9 : 6}
                      pathOptions={{ color: p.role === 'topic' ? '#b5651d' : '#2f6f5e', fillOpacity: 0.8 }}>
          <Tooltip>{`${p.label}: ${p.place} (${p.kind})`}</Tooltip>
        </CircleMarker>
      ))}
    </MapContainer>
  )
}
