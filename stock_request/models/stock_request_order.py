# -*- coding: utf-8 -*-
# Copyright 2018 Creu Blanca
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError, AccessError

REQUEST_STATES = [
    ('draft', 'Draft'),
    ('open', 'In progress'),
    ('done', 'Done'),
    ('cancel', 'Cancelled')]


class StockRequestOrder(models.Model):
    _name = 'stock.request.order'
    _description = 'Stock Request Order'
    _inherit = ['mail.thread']

    @api.model
    def default_get(self, fields):
        res = super(StockRequestOrder, self).default_get(fields)
        warehouse = None
        if 'warehouse_id' not in res and res.get('company_id'):
            warehouse = self.env['stock.warehouse'].search(
                [('company_id', '=', res['company_id'])], limit=1)
        if warehouse:
            res['warehouse_id'] = warehouse.id
            res['location_id'] = warehouse.lot_stock_id.id
        return res

    def _get_default_requested_by(self):
        return self.env['res.users'].browse(self.env.uid)

    name = fields.Char(
        'Name', copy=False, required=True, readonly=True,
        states={'draft': [('readonly', False)]},
        default='/')
    state = fields.Selection(selection=REQUEST_STATES, string='Status',
                             copy=False, default='draft', index=True,
                             readonly=True, track_visibility='onchange',
                             )
    requested_by = fields.Many2one(
        'res.users', 'Requested by', required=True,
        track_visibility='onchange',
        default=lambda s: s._get_default_requested_by(),
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse', 'Warehouse', readonly=True,
        ondelete="cascade", required=True,
        states={'draft': [('readonly', False)]})
    location_id = fields.Many2one(
        'stock.location', 'Location', readonly=True,
        domain=[('usage', 'in', ['internal', 'transit'])],
        ondelete="cascade", required=True,
        states={'draft': [('readonly', False)]},
    )
    procurement_group_id = fields.Many2one(
        'procurement.group', 'Procurement Group', readonly=True,
        states={'draft': [('readonly', False)]},
        help="Moves created through this stock request will be put in this "
             "procurement group. If none is given, the moves generated by "
             "procurement rules will be grouped into one big picking.",
    )
    company_id = fields.Many2one(
        'res.company', 'Company', required=True, readonly=True,
        states={'draft': [('readonly', False)]},
        default=lambda self: self.env['res.company']._company_default_get(
            'stock.request.order'),
    )
    expected_date = fields.Datetime(
        'Expected Date', default=fields.Datetime.now, index=True,
        required=True, readonly=True,
        states={'draft': [('readonly', False)]},
        help="Date when you expect to receive the goods.",
    )
    picking_policy = fields.Selection([
        ('direct', 'Receive each product when available'),
        ('one', 'Receive all products at once')],
        string='Shipping Policy', required=True, readonly=True,
        states={'draft': [('readonly', False)]},
        default='direct',
    )
    move_ids = fields.One2many(comodel_name='stock.move',
                               compute='_compute_move_ids',
                               string='Stock Moves', readonly=True,
                               )
    picking_ids = fields.One2many('stock.picking',
                                  compute='_compute_picking_ids',
                                  string='Pickings', readonly=True,
                                  )
    picking_count = fields.Integer(string='Delivery Orders',
                                   compute='_compute_picking_ids',
                                   readonly=True,
                                   )
    stock_request_ids = fields.One2many(
        'stock.request',
        inverse_name='order_id',
    )
    stock_request_count = fields.Integer(
        string='Stock requests',
        compute='_compute_stock_request_count',
        readonly=True,
    )

    _sql_constraints = [
        ('name_uniq', 'unique(name, company_id)',
         'Stock Request name must be unique'),
    ]

    @api.depends('stock_request_ids.allocation_ids')
    def _compute_picking_ids(self):
        for record in self:
            record.picking_ids = record.stock_request_ids.mapped('picking_ids')
            record.picking_count = len(record.picking_ids)

    @api.depends('stock_request_ids')
    def _compute_move_ids(self):
        for record in self:
            record.move_ids = record.stock_request_ids.mapped('move_ids')

    @api.depends('stock_request_ids')
    def _compute_stock_request_count(self):
        for record in self:
            record.stock_request_count = len(record.stock_request_ids)

    @api.onchange('requested_by')
    def onchange_requested_by(self):
        self.change_childs()

    @api.onchange('expected_date')
    def onchange_expected_date(self):
        self.change_childs()

    @api.onchange('picking_policy')
    def onchange_picking_policy(self):
        self.change_childs()

    @api.onchange('location_id')
    def onchange_location_id(self):
        if self.location_id:
            loc_wh = self.location_id.sudo().get_warehouse()
            if loc_wh and self.warehouse_id != loc_wh:
                self.warehouse_id = loc_wh
                self.with_context(
                    no_change_childs=True).onchange_warehouse_id()
        self.change_childs()

    @api.onchange('warehouse_id')
    def onchange_warehouse_id(self):
        if self.warehouse_id:
            # search with sudo because the user may not have permissions
            loc_wh = self.location_id.sudo().get_warehouse()
            if self.warehouse_id != loc_wh:
                self.location_id = self.warehouse_id.sudo().lot_stock_id
                self.with_context(no_change_childs=True).onchange_location_id()
            if self.warehouse_id.sudo().company_id != self.company_id:
                self.company_id = self.warehouse_id.company_id
                self.with_context(no_change_childs=True).onchange_company_id()
        self.change_childs()

    @api.onchange('procurement_group_id')
    def onchange_procurement_group_id(self):
        self.change_childs()

    @api.onchange('company_id')
    def onchange_company_id(self):
        if self.company_id and (
            not self.warehouse_id or
            self.warehouse_id.sudo().company_id != self.company_id
        ):
            self.warehouse_id = self.env['stock.warehouse'].search(
                [('company_id', '=', self.company_id.id)], limit=1)
            self.with_context(no_change_childs=True).onchange_warehouse_id()
        self.change_childs()
        return {
            'domain': {
                'warehouse_id': [('company_id', '=', self.company_id.id)]}}

    def change_childs(self):
        if not self._context.get('no_change_childs', False):
            for line in self.stock_request_ids:
                line.warehouse_id = self.warehouse_id
                line.location_id = self.location_id
                line.company_id = self.company_id
                line.picking_policy = self.picking_policy
                line.expected_date = self.expected_date
                line.requested_by = self.requested_by
                line.procurement_group_id = self.procurement_group_id

    @api.multi
    def action_confirm(self):
        if not self.procurement_group_id:
            proc = self.env['procurement.group'].create({'name': self.name})
            self.procurement_group_id = proc.id
        for line in self.stock_request_ids:
            line.action_confirm()
        self.state = 'open'
        return True

    def action_draft(self):
        for line in self.stock_request_ids:
            line.action_draft()
        self.state = 'draft'
        return True

    def action_cancel(self):
        for line in self.stock_request_ids:
            line.action_cancel()
        self.state = 'cancel'
        return True

    @api.multi
    def action_done_all(self):
        for obj in self:
            lines = obj.stock_request_ids.filtered(lambda r: r.state != 'done')
            lines.state = 'done'
            obj.action_done()

    def action_done(self):
        self.state = 'done'
        return True

    def check_done(self):
        if not self.stock_request_ids.filtered(lambda r: r.state != 'done'):
            self.action_done()
        return

    @api.multi
    def action_view_transfer(self):
        action = self.env.ref('stock.action_picking_tree_all').read()[0]

        pickings = self.mapped('picking_ids')
        if len(pickings) > 1:
            action['domain'] = [('id', 'in', pickings.ids)]
        elif pickings:
            action['views'] = [
                (self.env.ref('stock.view_picking_form').id, 'form')]
            action['res_id'] = pickings.id
        return action

    @api.multi
    def action_view_stock_requests(self):
        action = self.env.ref(
            'stock_request.action_stock_request_form').read()[0]
        if len(self.stock_request_ids) > 1:
            action['domain'] = [('order_id', 'in', self.ids)]
        elif self.stock_request_ids:
            action['views'] = [
                (self.env.ref(
                    'stock_request.view_stock_request_form').id, 'form')]
            action['res_id'] = self.stock_request_ids.id
        return action

    @api.model
    def create(self, vals):
        upd_vals = vals.copy()
        if upd_vals.get('name', '/') == '/':
            upd_vals['name'] = self.env['ir.sequence'].next_by_code(
                'stock.request.order')
        return super(StockRequestOrder, self).create(upd_vals)

    @api.multi
    def unlink(self):
        if self.filtered(lambda r: r.state != 'draft'):
            raise UserError(_('Only orders on draft state can be unlinked'))
        return super(StockRequestOrder, self).unlink()

    @api.constrains('warehouse_id', 'company_id')
    def _check_warehouse_company(self):
        if any(request.warehouse_id.company_id !=
                request.company_id for request in self):
            raise ValidationError(
                _('The company of the stock request must match with '
                  'that of the warehouse.'))

    @api.constrains('location_id', 'company_id')
    def _check_location_company(self):
        if any(request.location_id.company_id and
               request.location_id.company_id !=
               request.company_id for request in self):
            raise ValidationError(
                _('The company of the stock request must match with '
                  'that of the location.'))

    @api.model
    def _create_from_product_multiselect(self, products):
        if not products:
            return False
        if products._name not in ('product.product', 'product.template'):
            raise ValidationError(
                "This action only works in the context of products")
        if products._name == 'product.template':
            # search instead of mapped so we don't include archived variants
            products = self.env['product.product'].search([
                ('product_tmpl_id', 'in', products.ids)
            ])
        expected = self.default_get(['expected_date'])['expected_date']
        try:
            order = self.env['stock.request.order'].create(dict(
                expected_date=expected,
                stock_request_ids=[(0, 0, dict(
                    product_id=product.id,
                    product_uom_id=product.uom_id.id,
                    product_uom_qty=0.0,
                    expected_date=expected,
                )) for product in products]
            ))
        except AccessError:
            # TODO: if there is a nice way to hide the action from the
            # Action-menu if the user doesn't have the necessary rights,
            # that would be a better way of doing this
            raise UserError(_(
                "Unfortunately it seems you do not have the necessary rights "
                "for creating stock requests. Please contact your "
                "administrator."))
        action = self.env.ref('stock_request.stock_request_order_action'
                              ).read()[0]
        action['views'] = [(
            self.env.ref('stock_request.stock_request_order_form').id, 'form')]
        action['res_id'] = order.id
        return action
