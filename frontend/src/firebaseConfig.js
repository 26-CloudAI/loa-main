// Import the functions you need from the SDKs you need
import { initializeApp } from "firebase/app";
import { getAnalytics } from "firebase/analytics";
import { getAuth } from "firebase/auth";
import { getFirestore } from "firebase/firestore";

const firebaseConfig = {
  apiKey: "AIzaSyCWKBiGZu3xKxVj4JBrx8R0DSPQeuurg24",
  authDomain: "ai-arena-b2b4b.firebaseapp.com",
  projectId: "ai-arena-b2b4b",
  storageBucket: "ai-arena-b2b4b.firebasestorage.app",
  messagingSenderId: "802966355064",
  appId: "1:802966355064:web:6bed0bc5d8a6968ade018d",
  measurementId: "G-XNPG26DN70"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);

export const auth = getAuth(app);
export const db = getFirestore(app);
export default app;