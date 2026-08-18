import { useState, useEffect } from 'react';

interface DynamicDotProps {
  className?: string;
}

/**
 * 动态小点组件 - 显示动态变化的省略号
 */
export function DynamicDot({ className = '' }: DynamicDotProps) {
  const [dotCount, setDotCount] = useState('');

  useEffect(() => {
    const interval = setInterval(() => {
      setDotCount((count) => {
        if (count.length >= 3) {
          return '';
        }
        return count + '.';
      });
    }, 500);
    return () => clearInterval(interval);
  }, []);

  return <span className={className}>{dotCount}</span>;
}
