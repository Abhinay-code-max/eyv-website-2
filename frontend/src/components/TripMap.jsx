import React, { useEffect } from 'react';
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import { MAP_VIEW } from '../constants/testIds';

// Fix default marker icons - Leaflet bug with webpack
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

const customIcon = new L.Icon({
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41],
});

// Component that flies to a new center and invalidates size after mount
const FlyToLocation = ({ center, zoom }) => {
  const map = useMap();
  useEffect(() => {
    // invalidateSize ensures map renders correctly when container size changes
    setTimeout(() => map.invalidateSize(), 100);
  }, [map]);

  useEffect(() => {
    if (center && Array.isArray(center) && center.length === 2) {
      map.flyTo(center, zoom || 12, { duration: 1.2 });
    }
  }, [center, zoom, map]);

  return null;
};

const TripMap = ({ center, markers = [], height = '500px', zoom = 12 }) => {
  const validCenter =
    center && Array.isArray(center) && center.length === 2 && !isNaN(center[0]) && !isNaN(center[1])
      ? center
      : [20.5937, 78.9629]; // India centroid as default

  return (
    <div
      data-testid={MAP_VIEW.mapContainer}
      className="rounded-2xl overflow-hidden border border-[#E7E5E4]"
      style={{ height }}
    >
      <MapContainer
        center={validCenter}
        zoom={zoom}
        style={{ height: '100%', width: '100%' }}
        scrollWheelZoom={true}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          maxZoom={19}
        />
        <FlyToLocation center={validCenter} zoom={zoom} />
        {markers.map((marker, idx) => (
          <Marker key={idx} position={[marker.lat, marker.lng]} icon={customIcon}>
            <Popup>
              <div
                className="font-medium"
                style={{ fontFamily: 'Cormorant Garamond, serif', fontSize: '1.1rem' }}
              >
                {marker.title}
              </div>
              {marker.description && (
                <div className="text-sm text-[#57534E] mt-1">{marker.description}</div>
              )}
              {marker.price && (
                <div className="text-sm font-medium text-[#C47245] mt-1">{marker.price}</div>
              )}
            </Popup>
          </Marker>
        ))}
      </MapContainer>
    </div>
  );
};

export default TripMap;
