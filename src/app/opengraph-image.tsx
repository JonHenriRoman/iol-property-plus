import { ImageResponse } from 'next/og';

import { siteConfig } from '@/config/site';

export const size = { width: 1200, height: 630 };
export const contentType = 'image/png';
export const alt = siteConfig.name;

// Placeholder social preview. Replace with designed brand art when available.
const OpengraphImage = () => {
  return new ImageResponse(
    <div
      style={{
        background: siteConfig.backgroundColor,
        color: '#ffffff',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        justifyContent: 'center',
        padding: '80px',
        width: '100%',
      }}
    >
      <div style={{ display: 'flex', fontSize: 72, fontWeight: 700 }}>{siteConfig.name}</div>
      <div style={{ color: '#9fb3c8', display: 'flex', fontSize: 32, marginTop: 16 }}>
        {siteConfig.description}
      </div>
    </div>,
    size,
  );
};

export default OpengraphImage;
