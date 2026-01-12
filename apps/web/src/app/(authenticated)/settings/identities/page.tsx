'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

// Redirect old identities page to new connection page
export default function IdentitiesRedirect() {
  const router = useRouter();

  useEffect(() => {
    router.replace('/settings/connection');
  }, [router]);

  return null;
}
