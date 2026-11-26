# Frontend

The interface uses native JavaScript modules, HTML and CSS. The Python server serves
these files directly; running the application does not require Node.js or a build.

## Reading order

1. [index.html](index.html): main page and navigation areas.
2. [application-navigation.js](src/application-navigation.js): user actions and progress updates.
3. [browser-helpers.js](src/browser-helpers.js): safe text display and source links.
4. [Page renderers](src/page_renderers/README.md): individual Results and processing views.
5. [Report templates](report-templates/README.md): downloadable HTML reports.

Node.js is optional for formatting work:

```bash
npm ci --prefix frontend
npm --prefix frontend run check
```

Screenshots in the root README are actual saved application views, not mockups.
