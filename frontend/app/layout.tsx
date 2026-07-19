import "./globals.css";
import Nav from "@/components/Nav";
import { BetSlipProvider } from "@/lib/betslip";
import { SessionBootstrap } from "@/lib/session";

export const metadata = {
  title: "Predictor 26 — Sportsbook Mundial 2026",
  description: "Casa de predicciones del Mundial 2026 con puntos virtuales. Cuotas justas y valor esperado (EV) derivados de un modelo Dixon-Coles calibrado. Proyecto académico, sin dinero real.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <head>
        <meta name="theme-color" content="#6d40e6" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <SessionBootstrap />
        <BetSlipProvider>
          <div className="shell">
            <Nav />
            {children}
            <p className="disclaimer">
              Cuotas y probabilidades <b>estimadas por un modelo estadístico</b> (Dixon-Coles):
              son estimaciones, no garantías. Proyecto académico de software seguro —
              <b> puntos virtuales sin valor monetario</b>, sin dinero real ni apuestas reguladas.
            </p>
          </div>
        </BetSlipProvider>
      </body>
    </html>
  );
}
