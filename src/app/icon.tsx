import { ImageResponse } from 'next/og';

import { siteConfig } from '@/config/site';

export const size = { width: 32, height: 32 };
export const contentType = 'image/png';

// Placeholder favicon. Replace with a real brand asset in public/ when design provides one.
const Icon = () => {
  return new ImageResponse(
    <div
      style={{
        alignItems: 'center',
        background: siteConfig.backgroundColor,
        color: '#ffffff',
        display: 'flex',
        fontSize: 22,
        fontWeight: 700,
        height: '100%',
        justifyContent: 'center',
        width: '100%',
      }}
    >
      P
    </div>,
    size,
  );
};

export default Icon;
