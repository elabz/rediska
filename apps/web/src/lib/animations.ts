import { Variants, Transition } from 'framer-motion';

// Default transitions
export const transitions = {
  spring: {
    type: 'spring',
    stiffness: 400,
    damping: 30,
  } as Transition,
  springBouncy: {
    type: 'spring',
    stiffness: 500,
    damping: 25,
  } as Transition,
  springGentle: {
    type: 'spring',
    stiffness: 300,
    damping: 35,
  } as Transition,
  ease: {
    type: 'tween',
    ease: 'easeOut',
    duration: 0.3,
  } as Transition,
  easeIn: {
    type: 'tween',
    ease: 'easeIn',
    duration: 0.2,
  } as Transition,
  easeInOut: {
    type: 'tween',
    ease: 'easeInOut',
    duration: 0.3,
  } as Transition,
};

// Fade animations
export const fadeIn: Variants = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0 },
};

export const fadeInUp: Variants = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: 20 },
};

export const fadeInDown: Variants = {
  initial: { opacity: 0, y: -20 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -20 },
};

export const fadeInLeft: Variants = {
  initial: { opacity: 0, x: -20 },
  animate: { opacity: 1, x: 0 },
  exit: { opacity: 0, x: -20 },
};

export const fadeInRight: Variants = {
  initial: { opacity: 0, x: 20 },
  animate: { opacity: 1, x: 0 },
  exit: { opacity: 0, x: 20 },
};

// Scale animations
export const scaleIn: Variants = {
  initial: { opacity: 0, scale: 0.95 },
  animate: { opacity: 1, scale: 1 },
  exit: { opacity: 0, scale: 0.95 },
};

export const scaleInBounce: Variants = {
  initial: { opacity: 0, scale: 0.8 },
  animate: {
    opacity: 1,
    scale: 1,
    transition: transitions.springBouncy,
  },
  exit: { opacity: 0, scale: 0.8 },
};

// Slide animations
export const slideInFromLeft: Variants = {
  initial: { x: '-100%' },
  animate: { x: 0 },
  exit: { x: '-100%' },
};

export const slideInFromRight: Variants = {
  initial: { x: '100%' },
  animate: { x: 0 },
  exit: { x: '100%' },
};

export const slideInFromTop: Variants = {
  initial: { y: '-100%' },
  animate: { y: 0 },
  exit: { y: '-100%' },
};

export const slideInFromBottom: Variants = {
  initial: { y: '100%' },
  animate: { y: 0 },
  exit: { y: '100%' },
};

// Stagger container for animating children
export const staggerContainer: Variants = {
  initial: {},
  animate: {
    transition: {
      staggerChildren: 0.1,
      delayChildren: 0.1,
    },
  },
};

export const staggerContainerFast: Variants = {
  initial: {},
  animate: {
    transition: {
      staggerChildren: 0.05,
      delayChildren: 0.05,
    },
  },
};

// Stagger item (use as child of stagger container)
export const staggerItem: Variants = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
};

// Hover animations (for whileHover prop)
export const hoverScale = {
  scale: 1.02,
  transition: transitions.spring,
};

export const hoverLift = {
  y: -4,
  boxShadow: '0 10px 30px rgba(0,0,0,0.1)',
  transition: transitions.spring,
};

export const hoverGlow = {
  boxShadow: '0 0 30px rgba(59, 130, 246, 0.3)',
  transition: transitions.ease,
};

// Tap animations (for whileTap prop)
export const tapScale = {
  scale: 0.98,
  transition: transitions.spring,
};

export const tapPush = {
  scale: 0.95,
  transition: transitions.spring,
};

// Page transition presets
export const pageTransition: Variants = {
  initial: { opacity: 0, y: 20 },
  animate: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.4,
      ease: [0.25, 0.4, 0.25, 1],
    },
  },
  exit: {
    opacity: 0,
    y: -20,
    transition: {
      duration: 0.3,
      ease: [0.25, 0.4, 0.25, 1],
    },
  },
};

// Modal/dialog animations
export const modalOverlay: Variants = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0 },
};

export const modalContent: Variants = {
  initial: { opacity: 0, scale: 0.95, y: 10 },
  animate: {
    opacity: 1,
    scale: 1,
    y: 0,
    transition: transitions.springGentle,
  },
  exit: {
    opacity: 0,
    scale: 0.95,
    y: 10,
    transition: transitions.easeIn,
  },
};

// List item animations (for virtualized lists)
export const listItem: Variants = {
  initial: { opacity: 0, x: -20 },
  animate: { opacity: 1, x: 0 },
  exit: { opacity: 0, x: 20 },
};

// Card hover animation preset
export const cardHover = {
  rest: {
    scale: 1,
    boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)',
  },
  hover: {
    scale: 1.02,
    boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.1)',
    transition: transitions.spring,
  },
  tap: {
    scale: 0.98,
  },
};

// Button animation preset
export const buttonVariants: Variants = {
  rest: { scale: 1 },
  hover: { scale: 1.02 },
  tap: { scale: 0.98 },
};

// Skeleton pulse animation (CSS fallback also available)
export const skeletonPulse: Variants = {
  initial: { opacity: 0.5 },
  animate: {
    opacity: [0.5, 1, 0.5],
    transition: {
      duration: 1.5,
      repeat: Infinity,
      ease: 'easeInOut',
    },
  },
};

// Notification/toast animation
export const notification: Variants = {
  initial: { opacity: 0, y: -50, x: 0 },
  animate: {
    opacity: 1,
    y: 0,
    transition: transitions.springBouncy,
  },
  exit: {
    opacity: 0,
    y: -20,
    transition: transitions.ease,
  },
};

// Accordion/collapsible content
export const accordion: Variants = {
  initial: { height: 0, opacity: 0 },
  animate: {
    height: 'auto',
    opacity: 1,
    transition: {
      height: { duration: 0.3, ease: 'easeOut' },
      opacity: { duration: 0.2, delay: 0.1 },
    },
  },
  exit: {
    height: 0,
    opacity: 0,
    transition: {
      height: { duration: 0.2, ease: 'easeIn' },
      opacity: { duration: 0.1 },
    },
  },
};
