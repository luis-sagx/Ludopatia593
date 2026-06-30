import "./globals.css";
import Nav from "@/components/Nav";

export const metadata = {
  title: "Predictor Mundial 2026",
  description: "Predicciones probabilísticas con puntos virtuales — proyecto académico.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body>
        <Nav />
        <main>
          {children}
          <p className="disclaimer">
            Las predicciones son <b>probabilísticas, no garantías</b>. Proyecto académico,
            puntos virtuales sin valor monetario.
          </p>
        </main>
      </body>
    </html>
  );
}
