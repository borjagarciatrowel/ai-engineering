Borja (cliente): Queremos renovar el frontend de Trowelapp, nuestro SaaS para construcción. Funciona, pero el frontend está obsoleto: mezcla Blade, jQuery y algo de Vue 2, y cuesta mucho evolucionarlo.

Laura (proveedor): ¿Buscáis rediseño visual o reimplementación?

Borja: Reimplementación. Queremos frontend desacoplado del backend Laravel, consumiendo APIs REST, con TypeScript. Preferimos Vue 3.

Laura: ¿Qué módulos debe cubrir?

Borja: Login, dashboard, obras, presupuestos, certificaciones, partes de trabajo, documentos, contactos, usuarios y configuración. Para MVP: login, layout, dashboard básico, obras, presupuestos y partes.

Laura: ¿Qué incluye obras?

Borja: Listado con filtros, alta y edición, ficha de obra con pestañas, documentos, contactos y archivar.

Laura: ¿Y presupuestos?

Borja: Capítulos y partidas. Tabla editable para añadir, reordenar y modificar partidas, calcular totales, guardar borrador, duplicar presupuesto y exportar PDF. El PDF lo genera backend.

Laura: ¿Partes de trabajo?

Borja: Los operarios los rellenan desde móvil: obra, fecha, horas, materiales, descripción, fotos y firma. Responsive. Sin offline completo.

Laura: ¿Tenéis diseño?

Borja: Solo logo, colores y tipografías. Necesitamos UX/UI B2B y sistema básico de componentes.

Laura: ¿API documentada?

Borja: Parcialmente. Hay Swagger para algunos endpoints. Habría que auditar API y detectar endpoints faltantes.

Laura: ¿Migración progresiva?

Borja: Sí, que conviva con el frontend actual y se active por módulos.

Laura: ¿Requisitos técnicos?

Borja: Buen rendimiento, responsive, preparado para i18n, permisos por roles y tests básicos de flujos críticos.

Laura: ¿Qué queda fuera?

Borja: Billing, app nativa, Gantt, marketplace, offline completo e importación Excel.

Laura: Riesgos: API incompleta, autenticación, permisos, editor de presupuestos y móvil.

Borja: Correcto. Necesito estimación por fases. Objetivo: MVP en 3 meses y versión completa en 5 o 6.