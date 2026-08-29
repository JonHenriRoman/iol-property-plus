import { ImageResponse } from 'next/og';

import { siteConfig } from '@/config/site';

export const size = { width: 180, height: 180 };
export const contentType = 'image/png';

// Placeholder iOS home-screen icon. Replace with a real brand asset when design provides one.
const AppleIcon = () => {
  return new ImageResponse(
    <div
      style={{
        alignItems: 'center',
        background: siteConfig.backgroundColor,
        color: '#ffffff',
        display: 'flex',
        fontSize: 112,
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

export default AppleIcon;
