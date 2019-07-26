# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.addons import decimal_precision as dp


class StockRequestTemplate(models.Model):
    _name = "stock.request.template"

    name = fields.Char("Nombre", required=True)
    line_ids = fields.One2many(
        "stock.request.template.line", "template_id", string="Plantilla"
    )
    route_id = fields.Many2one("stock.location.route", string="Ruta")


class StockRequestTemplateLine(models.Model):
    _name = "stock.request.template.line"

    product_id = fields.Many2one(
        "product.product",
        "Producto",
        domain=[("type", "in", ["product", "consu"])],
        ondelete="cascade",
        required=True,
    )
    product_uom_id = fields.Many2one(
        "product.uom",
        "UdM",
        required=True,
        default=lambda self: self._context.get("product_uom_id", False),
    )
    product_uom_qty = fields.Float(
        "Cantidad", digits=dp.get_precision("Product Unit of Measure"), required=True
    )
    template_id = fields.Many2one("stock.request.template", string="Plantilla")

    @api.onchange("product_id")
    def onchange_product_id(self):
        res = {"domain": {}}
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id.id
            res["domain"]["product_uom_id"] = [
                ("category_id", "=", self.product_id.uom_id.category_id.id)
            ]
            return res
        res["domain"]["product_uom_id"] = []
        return res


class StockRequestOrder(models.Model):
    _inherit = "stock.request.order"

    template_id = fields.Many2one("stock.request.template", string="Plantilla")

    @api.onchange("template_id")
    def _onchange_template(self):
        if self.template_id:
            self.route_id = self.template_id.route_id

    @api.multi
    def load_template(self):
        self.ensure_one()
        self.stock_request_ids.unlink()
        for line in self.template_id.line_ids:
            data = {
                "product_id": line.product_id.id,
                "product_uom_id": line.product_uom_id.id,
                "product_uom_qty": line.product_uom_qty,
                "expected_date": self.expected_date,
                "picking_policy": self.picking_policy,
                "warehouse_id": self.warehouse_id.id,
                "location_id": self.location_id.id,
                "route_id": self.route_id.id,
                "company_id": self.company_id.id,
                "state": self.state,
                "order_id": self.id,
            }
            self.env["stock.request"].create(data)
