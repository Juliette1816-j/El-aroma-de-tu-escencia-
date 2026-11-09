import traceback, requests
from flask import Flask, render_template, request, redirect, url_for, jsonify
from config import get_connection
from datetime import datetime


app = Flask(__name__)


def query(sql, params=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params or [])
    rows = cursor.fetchall()
    conn.close()
    return rows


def scalar(sql, params=None):
    """Retorna el primer valor escalar. Devuelve 0 si la tabla está vacía o el resultado es NULL."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params or [])
    row = cursor.fetchone()
    conn.close()
    if row is None or row[0] is None:
        return 0
    return row[0]


def execute(sql, params=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params or [])
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────
# DASHBOARD
# ──────────────────────────────────────────────
@app.route('/')
def dashboard():
    try:
        total_materias        = scalar("SELECT COUNT(*) FROM MateriasPrimas")
        total_lotes           = scalar("SELECT COUNT(*) FROM LotesProduccion")
        total_experimentos    = scalar("SELECT COUNT(*) FROM Experimentos")
        total_certificaciones = scalar("SELECT COUNT(*) FROM Certificaciones")

        author    = scalar("SELECT COUNT(*) FROM Certificaciones WHERE NivelCertificacion='AUTHOR'")
        signature = scalar("SELECT COUNT(*) FROM Certificaciones WHERE NivelCertificacion='SIGNATURE'")
        essential = scalar("SELECT COUNT(*) FROM Certificaciones WHERE NivelCertificacion='ESSENTIAL'")
        rechazadas = scalar("SELECT COUNT(*) FROM Certificaciones WHERE NivelCertificacion IS NULL")
        promedio_puntaje = scalar("SELECT ISNULL(AVG(CAST(PuntajeFinal AS FLOAT)),0) FROM Certificaciones")

        porcentaje_exito = 0
        if total_certificaciones > 0:
            porcentaje_exito = round(((author + signature + essential) / total_certificaciones) * 100, 1)

        alertas = scalar("SELECT COUNT(*) FROM MateriasPrimas WHERE StockActual <= StockMinimo")

        # Producción mensual del año actual
        anio_actual = datetime.now().year
        grafica_produccion = []
        for mes in range(1, 13):
            val = scalar(
                "SELECT ISNULL(SUM(CantidadProducida),0) FROM Produccion "
                "WHERE MONTH(FechaProduccion)=? AND YEAR(FechaProduccion)=?",
                [mes, anio_actual]
            )
            grafica_produccion.append(int(val))

        stats = {
            'materias':         total_materias,
            'lotes':            total_lotes,
            'experimentos':     total_experimentos,
            'certificaciones':  total_certificaciones,
            'author':           author,
            'signature':        signature,
            'essential':        essential,
            'rechazadas':       rechazadas,
            'promedio_puntaje': round(float(promedio_puntaje), 1),
            'porcentaje_exito': porcentaje_exito,
            'alertas':          alertas,
        }

        # 🤖 IA AUTOMÁTICA AL CARGAR DASHBOARD
        try:
            ia_auto = requests.post(
                "http://localhost:5000/ia/consulta",
                json={"mensaje": "Analiza automáticamente toda la empresa"}
            ).json().get("respuesta", "")
        except:
            ia_auto = "No disponible"


        return render_template(
            'dashboard.html',
            titulo='Dashboard',
            stats=stats,
            grafica_produccion=grafica_produccion,
            certificaciones=[],
            materias_criticas=[],
            now=datetime.now().strftime('%d/%m/%Y %H:%M')
        )
    except Exception:
        return "<pre>" + traceback.format_exc() + "</pre>"


# ──────────────────────────────────────────────
# INVENTARIO
# ──────────────────────────────────────────────
@app.route('/inventario')
def inventario():
    try:
        materias = query(
            "SELECT Codigo, Nombre, Categoria, StockActual, StockMinimo, "
            "UnidadMedida, CostoUnitario, MateriaPrimaID "
            "FROM MateriasPrimas ORDER BY Categoria, Nombre"
        )
        proveedores = query(
            "SELECT ProveedorID, Nombre FROM Proveedores WHERE Activo=1 ORDER BY Nombre"
        )
        categorias = sorted(list(set([m[2] for m in materias if m[2]])))
        stats = {
            'total':    len(materias),
            'criticos': sum(1 for m in materias if m[3] is not None and m[4] is not None and 0 < m[3] <= m[4]),
            'agotados': sum(1 for m in materias if m[3] == 0),
            'ok':       sum(1 for m in materias if m[3] is not None and m[4] is not None and m[3] > m[4]),
        }
        mes_actual  = datetime.now().month
        anio_actual = datetime.now().year
        query_top = """
            SELECT TOP 3 m.Codigo, m.Nombre, SUM(dc.Cantidad) as TotalGastado, m.UnidadMedida
            FROM DetalleCompras dc
            JOIN MateriasPrimas m ON dc.MateriaPrimaID = m.MateriaPrimaID
            JOIN Compras c ON dc.CompraID = c.CompraID
            WHERE MONTH(c.FechaCompra) = ? AND YEAR(c.FechaCompra) = ?
            GROUP BY m.Codigo, m.Nombre, m.UnidadMedida
            ORDER BY TotalGastado DESC
        """
        top_materias = query(query_top, [mes_actual, anio_actual])

        return render_template('inventario/materias.html',
            titulo='Inventario',
            materias=materias,
            proveedores=proveedores,
            categorias=categorias,
            stats=stats,
            top_materias=top_materias
        )
    except Exception:
        return "<pre>" + traceback.format_exc() + "</pre>"


@app.route('/inventario/nueva-materia', methods=['POST'])
def nueva_materia():
    execute(
        "INSERT INTO MateriasPrimas "
        "(Codigo, Nombre, Categoria, UnidadMedida, StockActual, StockMinimo, CostoUnitario, ProveedorID) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            request.form.get('codigo'),
            request.form.get('nombre'),
            request.form.get('categoria'),
            request.form.get('unidad'),
            request.form.get('stock_actual', 0),
            request.form.get('stock_minimo', 0),
            request.form.get('costo', 0),
            request.form.get('proveedor_id') or None
        ]
    )
    return redirect(url_for('inventario'))


@app.route('/inventario/editar-materia', methods=['POST'])
def editar_materia():
    execute(
        "UPDATE MateriasPrimas SET "
        "Codigo=?, Nombre=?, Categoria=?, UnidadMedida=?, "
        "StockActual=?, StockMinimo=?, CostoUnitario=? "
        "WHERE MateriaPrimaID=?",
        [
            request.form.get('codigo'),
            request.form.get('nombre'),
            request.form.get('categoria'),
            request.form.get('unidad'),
            request.form.get('stock_actual'),
            request.form.get('stock_minimo'),
            request.form.get('costo'),
            request.form.get('id')
        ]
    )
    return redirect(url_for('inventario'))


@app.route('/inventario/get-materia/<int:materia_id>')
def get_materia(materia_id):
    """AJAX: devuelve datos de una materia para el modal de edición."""
    rows = query(
        "SELECT MateriaPrimaID, Codigo, Nombre, Categoria, UnidadMedida, "
        "StockActual, StockMinimo, CostoUnitario, ProveedorID "
        "FROM MateriasPrimas WHERE MateriaPrimaID=?",
        [materia_id]
    )
    if not rows:
        return jsonify({'error': 'No encontrado'}), 404
    m = rows[0]
    return jsonify({
        'id':           m[0],
        'codigo':       m[1],
        'nombre':       m[2],
        'categoria':    m[3],
        'unidad':       m[4],
        'stock_actual': float(m[5]) if m[5] is not None else 0,
        'stock_minimo': float(m[6]) if m[6] is not None else 0,
        'costo':        float(m[7]) if m[7] is not None else 0,
        'proveedor_id': m[8],
    })


# ──────────────────────────────────────────────
# COMPRAS
# ──────────────────────────────────────────────
@app.route('/compras')
def compras():
    try:
        compras_list = query(
            "SELECT c.CompraID, c.NumeroFactura, p.Nombre, "
            "c.FechaCompra, c.TotalCompra, c.Estado "
            "FROM Compras c "
            "LEFT JOIN Proveedores p ON c.ProveedorID = p.ProveedorID "
            "ORDER BY c.CompraID DESC"
        )
        proveedores = query(
            "SELECT ProveedorID, Nombre FROM Proveedores WHERE Activo=1 ORDER BY Nombre"
        )
        materias = query(
            "SELECT MateriaPrimaID, Nombre, UnidadMedida FROM MateriasPrimas ORDER BY Nombre"
        )
        mes_actual  = datetime.now().month
        anio_actual = datetime.now().year
        stats = {
            'total':      len(compras_list),
            'pendientes': sum(1 for c in compras_list if c[5] == 'PENDIENTE'),
            'recibidas':  sum(1 for c in compras_list if c[5] == 'RECIBIDA'),
            'total_mes':  "{:,.0f}".format(sum(
                c[4] for c in compras_list
                if c[4] and c[3] and c[3].month == mes_actual and c[3].year == anio_actual
            ))
        }
        return render_template('compras/compras.html',
            titulo='Compras',
            compras=compras_list,
            proveedores=proveedores,
            materias=materias,
            stats=stats
        )
    except Exception:
        return "<pre>" + traceback.format_exc() + "</pre>"


@app.route('/compras/nueva', methods=['POST'])
def nueva_compra():
    factura   = request.form.get('factura')
    proveedor = request.form.get('proveedor_id')
    fecha     = request.form.get('fecha')
    estado    = request.form.get('estado')
    total     = request.form.get('total', 0)

    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO Compras (NumeroFactura, ProveedorID, FechaCompra, TotalCompra, Estado) "
        "VALUES (?, ?, ?, ?, ?)",
        [factura, proveedor, fecha, total, estado]
    )
    cursor.execute("SELECT @@IDENTITY")
    compra_id = int(cursor.fetchone()[0])

    materias_ids = request.form.getlist('materia_id[]')
    cantidades   = request.form.getlist('cantidad[]')
    costos       = request.form.getlist('costo[]')

    for i, mat_id in enumerate(materias_ids):
        if not mat_id:
            continue
        cant  = float(cantidades[i]) if cantidades[i] else 0
        costo = float(costos[i])     if costos[i]     else 0
        cursor.execute(
            "INSERT INTO DetalleCompras (CompraID, MateriaPrimaID, Cantidad, CostoUnitario, Subtotal) "
            "VALUES (?, ?, ?, ?, ?)",
            [compra_id, mat_id, cant, costo, cant * costo]
        )

    conn.commit()
    conn.close()
    return redirect(url_for('compras'))


@app.route('/compras/<int:compra_id>')
def detalle_compra(compra_id):
    try:
        compra = query(
            "SELECT c.CompraID, c.NumeroFactura, p.Nombre, "
            "c.FechaCompra, c.TotalCompra, c.Estado "
            "FROM Compras c "
            "LEFT JOIN Proveedores p ON c.ProveedorID = p.ProveedorID "
            "WHERE c.CompraID = ?", [compra_id]
        )
        if not compra:
            return redirect(url_for('compras'))
        detalle = query(
            "SELECT m.Nombre, d.Cantidad, m.UnidadMedida, d.CostoUnitario, d.Subtotal "
            "FROM DetalleCompras d "
            "JOIN MateriasPrimas m ON d.MateriaPrimaID = m.MateriaPrimaID "
            "WHERE d.CompraID = ?", [compra_id]
        )
        return render_template('compras/detalle.html',
            titulo='Detalle Compra',
            compra=compra[0],
            detalle=detalle
        )
    except Exception:
        return "<pre>" + traceback.format_exc() + "</pre>"


# ──────────────────────────────────────────────
# PRODUCCION
# ──────────────────────────────────────────────
@app.route('/produccion')
def produccion():
    try:
        producciones = query(
            "SELECT ISNULL(lp.CodigoLote,'Sin lote'), pr.Nombre, f.CodigoFormula, "
            "prod.CantidadProducida, prod.FechaProduccion, "
            "prod.FechaCurado, prod.Estado, prod.ProduccionID "
            "FROM Produccion prod "
            "JOIN Productos pr  ON prod.ProductoID = pr.ProductoID "
            "JOIN Formulas f    ON prod.FormulaID  = f.FormulaID "
            "LEFT JOIN LotesProduccion lp ON lp.ProductoID = prod.ProductoID "
            "AND lp.FormulaID = prod.FormulaID "
            "ORDER BY prod.ProduccionID DESC"
        )
        productos = query(
            "SELECT ProductoID, Codigo, Nombre FROM Productos WHERE Activo=1 ORDER BY Nombre"
        )
        formulas = query(
            "SELECT FormulaID, CodigoFormula, ProductoID, VersionFormula FROM Formulas ORDER BY CodigoFormula"
        )
        stats = {
            'total':      len(producciones),
            'en_curado':  sum(1 for p in producciones if p[6] == 'EN_CURADO'),
            'terminados': sum(1 for p in producciones if p[6] == 'TERMINADO'),
            'unidades':   sum(p[3] for p in producciones if p[3]),
        }
        return render_template('produccion/produccion.html',
            titulo='Producción',
            producciones=producciones,
            productos=productos,
            formulas=formulas,
            stats=stats
        )
    except Exception:
        return "<pre>" + traceback.format_exc() + "</pre>"


@app.route('/produccion/nueva', methods=['POST'])
def nueva_produccion():
    producto_id      = request.form.get('producto_id')
    formula_id       = request.form.get('formula_id')
    cantidad         = request.form.get('cantidad')
    estado           = request.form.get('estado')
    fecha_produccion = request.form.get('fecha_produccion')
    fecha_curado     = request.form.get('fecha_curado') or None

    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO Produccion "
        "(ProductoID, FormulaID, CantidadProducida, Estado, FechaProduccion, FechaCurado) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [producto_id, formula_id, cantidad, estado, fecha_produccion, fecha_curado]
    )
    cursor.execute("SELECT @@IDENTITY")
    prod_id = int(cursor.fetchone()[0])

    codigo = f"LOT-{datetime.now().year}-{str(prod_id).zfill(4)}"
    cursor.execute(
        "INSERT INTO LotesProduccion "
        "(CodigoLote, ProductoID, FormulaID, CantidadProducida, Estado, FechaProduccion) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [codigo, producto_id, formula_id, cantidad, estado, fecha_produccion]
    )
    conn.commit()
    conn.close()
    return redirect(url_for('produccion'))


@app.route('/produccion/cambiar-estado', methods=['POST'])
def cambiar_estado_produccion():
    execute(
        "UPDATE Produccion SET Estado=? WHERE ProduccionID=?",
        [request.form.get('estado'), request.form.get('produccion_id')]
    )
    return redirect(url_for('produccion'))


# ──────────────────────────────────────────────
# LABORATORIO
# ──────────────────────────────────────────────
@app.route('/laboratorio')
def laboratorio():
    try:
        experimentos = query(
            "SELECT e.Codigo, e.Nombre, e.Objetivo, e.Responsable, "
            "e.FechaInicio, e.Estado, e.ExperimentoID "
            "FROM Experimentos e ORDER BY e.ExperimentoID DESC"
        )
        pruebas = query(
            "SELECT p.Codigo, e.Nombre, p.TipoPrueba, "
            "p.FechaPrueba, p.Responsable, p.PruebaID "
            "FROM PruebasLaboratorio p "
            "LEFT JOIN Experimentos e ON p.ExperimentoID = e.ExperimentoID "
            "ORDER BY p.PruebaID DESC"
        )
        colecciones = query("SELECT ColeccionID, Nombre FROM Colecciones ORDER BY Nombre")
        lotes       = query("SELECT LoteID, CodigoLote FROM LotesProduccion ORDER BY LoteID DESC")
        stats = {
            'total':       len(experimentos),
            'en_progreso': sum(1 for e in experimentos if e[5] == 'EN_PROGRESO'),
            'exitosos':    sum(1 for e in experimentos if e[5] == 'EXITOSO'),
            'pruebas':     len(pruebas),
        }
        return render_template('laboratorio/laboratorio.html',
            titulo='Laboratorio',
            experimentos=experimentos,
            pruebas=pruebas,
            colecciones=colecciones,
            lotes=lotes,
            stats=stats
        )
    except Exception:
        return "<pre>" + traceback.format_exc() + "</pre>"


@app.route('/laboratorio/nuevo-experimento', methods=['POST'])
def nuevo_experimento():
    execute(
        "INSERT INTO Experimentos "
        "(Codigo, Nombre, Objetivo, ColeccionID, Responsable, FechaInicio, Estado, Conclusiones) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            request.form.get('codigo'),
            request.form.get('nombre'),
            request.form.get('objetivo'),
            request.form.get('coleccion_id') or None,
            request.form.get('responsable'),
            request.form.get('fecha_inicio') or None,
            request.form.get('estado'),
            request.form.get('conclusiones'),
        ]
    )
    return redirect(url_for('laboratorio'))


@app.route('/laboratorio/nueva-prueba', methods=['POST'])
def nueva_prueba():
    execute(
        "INSERT INTO PruebasLaboratorio "
        "(Codigo, ExperimentoID, LoteID, TipoPrueba, FechaPrueba, Responsable, Observaciones) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            request.form.get('codigo'),
            request.form.get('experimento_id'),
            request.form.get('lote_id') or None,
            request.form.get('tipo_prueba'),
            request.form.get('fecha_prueba') or None,
            request.form.get('responsable'),
            request.form.get('observaciones'),
        ]
    )
    return redirect(url_for('laboratorio'))


@app.route('/laboratorio/nuevo-resultado', methods=['POST'])
def nuevo_resultado():
    execute(
        "INSERT INTO ResultadosPrueba "
        "(PruebaID, IntensidadFrio, IntensidadEncendida, Persistencia, Difusion, "
        "TiempoQuemado, Uniformidad, TunelCera, Residuos, "
        "Color, Acabado, Textura, Imperfecciones, Notas) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            request.form.get('prueba_id'),
            request.form.get('intensidad_frio'),
            request.form.get('intensidad_encendida'),
            request.form.get('persistencia'),
            request.form.get('difusion'),
            request.form.get('tiempo_quemado'),
            request.form.get('uniformidad'),
            request.form.get('tunel_cera'),
            request.form.get('residuos'),
            request.form.get('color'),
            request.form.get('acabado'),
            request.form.get('textura'),
            request.form.get('imperfecciones'),
            request.form.get('notas'),
        ]
    )
    return redirect(url_for('laboratorio'))


@app.route('/laboratorio/pruebas-experimento/<int:exp_id>')
def pruebas_experimento(exp_id):
    pruebas = query(
        "SELECT p.Codigo, p.TipoPrueba, p.FechaPrueba, "
        "r.PuntajeFinal, c.NivelCertificacion "
        "FROM PruebasLaboratorio p "
        "LEFT JOIN ResultadosPrueba r ON r.PruebaID = p.PruebaID "
        "LEFT JOIN Certificaciones c  ON c.PruebaID = p.PruebaID "
        "WHERE p.ExperimentoID = ? ORDER BY p.PruebaID DESC",
        [exp_id]
    )
    resultado = [
        {
            'codigo':  p[0],
            'tipo':    p[1] or '—',
            'fecha':   p[2].strftime('%d/%m/%Y') if p[2] else '—',
            'puntaje': str(p[3]) if p[3] else None,
            'nivel':   p[4]
        }
        for p in pruebas
    ]
    return jsonify(resultado)


@app.route('/laboratorio/cambiar-estado-experimento', methods=['POST'])
def cambiar_estado_experimento():
    execute(
        "UPDATE Experimentos SET Estado=?, Conclusiones=? WHERE ExperimentoID=?",
        [
            request.form.get('estado'),
            request.form.get('conclusiones') or None,
            request.form.get('experimento_id')
        ]
    )
    return redirect(url_for('laboratorio'))


# ──────────────────────────────────────────────
# CERTIFICACIONES
# ──────────────────────────────────────────────
@app.route('/certificaciones')
def certificaciones():
    try:
        certs = query(
            "SELECT c.Codigo, lp.CodigoLote, c.PuntajeFinal, "
            "c.NivelCertificacion, c.TipoCertificacion, c.FechaCertificacion "
            "FROM Certificaciones c "
            "LEFT JOIN LotesProduccion lp ON c.LoteID = lp.LoteID "
            "ORDER BY c.CertificacionID DESC"
        )
        stats = {
            'total':     len(certs),
            'author':    sum(1 for c in certs if c[3] == 'AUTHOR'),
            'signature': sum(1 for c in certs if c[3] == 'SIGNATURE'),
            'essential': sum(1 for c in certs if c[3] == 'ESSENTIAL'),
        }
        return render_template('laboratorio/certificaciones.html',
            titulo='Certificaciones',
            certificaciones=certs,
            stats=stats
        )
    except Exception:
        return "<pre>" + traceback.format_exc() + "</pre>"


# ──────────────────────────────────────────────
# CATÁLOGO
# ──────────────────────────────────────────────
@app.route('/catalogo')
def catalogo():
    try:
        productos = query(
            "SELECT p.ProductoID, p.Codigo, p.Nombre, p.Descripcion, "
            "p.PrecioVenta, p.Activo, c.Nombre as Coleccion "
            "FROM Productos p "
            "LEFT JOIN Colecciones c ON p.ColeccionID = c.ColeccionID "
            "WHERE p.Activo=1 ORDER BY c.Nombre, p.Nombre"
        )
        colecciones = query("SELECT ColeccionID, Nombre FROM Colecciones ORDER BY Nombre")
        stats = {
            'total':       len(productos),
            'colecciones': len(colecciones),
        }
        return render_template('catalogo/catalogo.html',
            titulo='Catálogo',
            productos=productos,
            colecciones=colecciones,
            stats=stats
        )
    except Exception:
        return "<pre>" + traceback.format_exc() + "</pre>"


# ──────────────────────────────────────────────
# VENTAS
# ──────────────────────────────────────────────
@app.route('/ventas')
def ventas():
    try:
        ventas_list = query(
            "SELECT v.VentaID, v.NumeroVenta, cl.Nombre, "
            "v.FechaVenta, v.Total, v.Estado "
            "FROM Ventas v "
            "LEFT JOIN Clientes cl ON v.ClienteID = cl.ClienteID "
            "ORDER BY v.VentaID DESC"
        )
        clientes_list = query(
            "SELECT ClienteID, Nombre FROM Clientes WHERE Activo=1 ORDER BY Nombre"
        )
        productos = query(
            "SELECT ProductoID, Codigo, Nombre, PrecioVenta FROM Productos WHERE Activo=1 ORDER BY Nombre"
        )
        mes_actual  = datetime.now().month
        anio_actual = datetime.now().year
        stats = {
            'total':      len(ventas_list),
            'pendientes': sum(1 for v in ventas_list if v[5] == 'PENDIENTE'),
            'completadas': sum(1 for v in ventas_list if v[5] == 'COMPLETADA'),
            'total_mes':  "{:,.0f}".format(sum(
                v[4] for v in ventas_list
                if v[4] and v[3] and v[3].month == mes_actual and v[3].year == anio_actual
            ))
        }
        return render_template('ventas/ventas.html',
            titulo='Ventas',
            ventas=ventas_list,
            clientes=clientes_list,
            productos=productos,
            stats=stats
        )
    except Exception:
        return "<pre>" + traceback.format_exc() + "</pre>"


@app.route('/ventas/nueva', methods=['POST'])
def nueva_venta():
    cliente_id = request.form.get('cliente_id')
    fecha      = request.form.get('fecha')
    estado     = request.form.get('estado', 'PENDIENTE')
    total      = request.form.get('total', 0)
    numero     = f"VTA-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO Ventas (NumeroVenta, ClienteID, FechaVenta, Total, Estado) VALUES (?, ?, ?, ?, ?)",
        [numero, cliente_id, fecha, total, estado]
    )
    cursor.execute("SELECT @@IDENTITY")
    venta_id = int(cursor.fetchone()[0])

    productos_ids = request.form.getlist('producto_id[]')
    cantidades    = request.form.getlist('cantidad[]')
    precios       = request.form.getlist('precio[]')

    for i, prod_id in enumerate(productos_ids):
        if not prod_id:
            continue
        cant   = float(cantidades[i]) if cantidades[i] else 0
        precio = float(precios[i])    if precios[i]    else 0
        cursor.execute(
            "INSERT INTO DetalleVentas (VentaID, ProductoID, Cantidad, PrecioUnitario, Subtotal) "
            "VALUES (?, ?, ?, ?, ?)",
            [venta_id, prod_id, cant, precio, cant * precio]
        )

    conn.commit()
    conn.close()
    return redirect(url_for('ventas'))


# ──────────────────────────────────────────────
# CLIENTES
# ──────────────────────────────────────────────
@app.route('/clientes')
def clientes():
    try:
        clientes_list = query(
            "SELECT ClienteID, Nombre, Email, Telefono, Ciudad, "
            "FechaRegistro, Activo "
            "FROM Clientes ORDER BY Nombre"
        )
        stats = {
            'total':   len(clientes_list),
            'activos': sum(1 for c in clientes_list if c[6] == 1),
        }
        return render_template('clientes/clientes.html',
            titulo='Clientes',
            clientes=clientes_list,
            stats=stats
        )
    except Exception:
        return "<pre>" + traceback.format_exc() + "</pre>"


@app.route('/clientes/nuevo', methods=['POST'])
def nuevo_cliente():
    execute(
        "INSERT INTO Clientes (Nombre, Email, Telefono, Ciudad, Activo) VALUES (?, ?, ?, ?, 1)",
        [
            request.form.get('nombre'),
            request.form.get('email'),
            request.form.get('telefono'),
            request.form.get('ciudad'),
        ]
    )
    return redirect(url_for('clientes'))


@app.route('/clientes/get/<int:cliente_id>')
def get_cliente(cliente_id):
    rows = query(
        "SELECT ClienteID, Nombre, Email, Telefono, Ciudad FROM Clientes WHERE ClienteID=?",
        [cliente_id]
    )
    if not rows:
        return jsonify({'error': 'No encontrado'}), 404
    c = rows[0]
    return jsonify({'id': c[0], 'nombre': c[1], 'email': c[2], 'telefono': c[3], 'ciudad': c[4]})


@app.route('/clientes/editar', methods=['POST'])
def editar_cliente():
    execute(
        "UPDATE Clientes SET Nombre=?, Email=?, Telefono=?, Ciudad=? WHERE ClienteID=?",
        [
            request.form.get('nombre'),
            request.form.get('email'),
            request.form.get('telefono'),
            request.form.get('ciudad'),
            request.form.get('id'),
        ]
    )
    return redirect(url_for('clientes'))


# ──────────────────────────────────────────────
# REDIRECCION PRUEBAS
# ──────────────────────────────────────────────
@app.route('/pruebas')
def pruebas_redirect():
    return redirect(url_for('laboratorio'))


# ──────────────────────────────────────────────
# IA - ASISTENTE JJJW
# ──────────────────────────────────────────────
@app.route('/ia/consulta', methods=['POST'])
def ia_consulta():
    try:
        data = request.get_json()
        mensaje = data.get('mensaje', '').lower()

        conn = get_connection()
        cursor = conn.cursor()

        # 📊 DATOS EMPRESARIALES

        cursor.execute("SELECT TOP 5 Nombre, Ciudad FROM Clientes WHERE Activo=1")
        clientes = cursor.fetchall()

        cursor.execute("""
            SELECT TOP 5 NumeroVenta, Total, Estado 
            FROM Ventas ORDER BY FechaVenta DESC
        """)
        ventas = cursor.fetchall()

        cursor.execute("""
            SELECT TOP 5 Nombre, StockActual, StockMinimo 
            FROM MateriasPrimas 
            WHERE StockActual <= StockMinimo
        """)
        stock = cursor.fetchall()

        cursor.execute("""
            SELECT TOP 5 Estado, CantidadProducida 
            FROM Produccion ORDER BY FechaProduccion DESC
        """)
        produccion = cursor.fetchall()

        conn.close()

        # 🚨 ALERTAS AUTOMÁTICAS

        alertas = []

        if stock:
            alertas.append("Stock crítico en materias primas")

        if any(v[2] == 'PENDIENTE' for v in ventas):
            alertas.append("Ventas pendientes sin cerrar")

        if any(p[0] == 'EN_CURADO' for p in produccion):
            alertas.append("Producción aún en proceso (curado)")

        # 🧠 PROMPT NIVEL DIOS

        prompt = f"""
Eres un DIRECTOR DE EMPRESA experto en operaciones.

Tu trabajo es analizar el negocio automáticamente.

Debes:
- Detectar problemas
- Explicar causas
- Dar decisiones claras
- Priorizar acciones
- Diagnosticar
- Sugiere acciones concretas

DATOS:

Clientes:
{clientes}

Ventas:
{ventas}

Inventario crítico:
{stock}

Producción:
{produccion}

Alertas:
{alertas}

Consulta del usuario:
{mensaje}
"""

        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "llama3",
                "prompt": prompt,
                "stream": False
            }
        )

        respuesta = response.json().get("response", "")

        return jsonify({"respuesta": respuesta})

    except Exception as e:
        return jsonify({
            "error": str(e),
            "trace": traceback.format_exc()
        }), 500


if __name__ == '__main__':
    app.run(debug=True)
