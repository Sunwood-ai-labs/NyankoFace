import { nyankoFaceNavigation } from '@/lib/navigation';

export default function BrandMark({ className = '' }: { className?: string }) {
  return (
    <span className={`nyankoface-brand-mark ${className}`} aria-hidden="true">
      <img src={nyankoFaceNavigation.brand.markSrc} alt="" />
    </span>
  );
}
