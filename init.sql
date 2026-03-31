-- Tabla para almacenar las estadísticas de los equipos (Sincronizada por /actualizar)
CREATE TABLE IF NOT EXISTS stats_equipos (
    id_api INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    goles_favor_avg DECIMAL(4,2) DEFAULT 1.50,
    goles_contra_avg DECIMAL(4,2) DEFAULT 1.50,
    partidos_jugados INTEGER DEFAULT 0,
    ultima_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla para guardar el historial de predicciones del Oráculo
CREATE TABLE IF NOT EXISTS predicciones (
    id SERIAL PRIMARY KEY,
    deporte TEXT DEFAULT 'Fútbol',
    equipo_local TEXT NOT NULL,
    equipo_visitante TEXT NOT NULL,
    prediccion TEXT NOT NULL,
    fecha DATE DEFAULT CURRENT_DATE
);

-- Índices para búsqueda rápida por nombre de equipo
CREATE INDEX IF NOT EXISTS idx_nombre_equipo ON stats_equipos(nombre);
