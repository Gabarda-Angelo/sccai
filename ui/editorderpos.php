<?php
ob_start(); 
// Set the default timezone to Philippines time
date_default_timezone_set('Asia/Manila');

include_once 'connectdb.php';
session_start();
include_once "header.php";

// Determine if we are in edit mode by checking if "id" is passed via GET
$edit_mode = false;
$order_id = null;
$invoice = [];
$invoice_details = [];
$order_items = []; // Array to hold preloaded order items for JavaScript

if (isset($_GET['id']) && is_numeric($_GET['id'])) {
    $edit_mode = true;
    $order_id = (int) $_GET['id'];

    // Load existing invoice data from the "invoices" table
    $stmt = $pdo->prepare("SELECT * FROM invoices WHERE invoice_id = :id");
    $stmt->bindParam(':id', $order_id, PDO::PARAM_INT);
    $stmt->execute();
    $invoice = $stmt->fetch(PDO::FETCH_ASSOC);

    // Load invoice details with additional product data by joining products
    $stmt2 = $pdo->prepare("SELECT d.*, p.product_name, p.stock, p.sale_price 
                            FROM invoice_details d 
                            JOIN products p ON d.product_id = p.product_id 
                            WHERE d.invoice_id = :id");
    $stmt2->bindParam(':id', $order_id, PDO::PARAM_INT);
    $stmt2->execute();
    $invoice_details = $stmt2->fetchAll(PDO::FETCH_ASSOC);

    // Transform the result into the structure expected by the JavaScript:
    // Each item should have: product_id, product_name, stock, sale_price, qty, total
    foreach ($invoice_details as $detail) {
        $order_items[] = [
            'product_id'   => (int)$detail['product_id'],
            'product_name' => $detail['product_name'],
            'stock'        => (int)$detail['stock'],
            'sale_price'   => (float)$detail['sale_price'],
            'qty'          => (int)$detail['quantity'],
            'total'        => (float)$detail['total_price']
        ];
    }
}

// Function to populate product dropdown
function fill_product($pdo) {
    $output = '';
    $select = $pdo->prepare("SELECT product_id, product_name FROM products ORDER BY product_name ASC");
    $select->execute();
    while ($row = $select->fetch(PDO::FETCH_ASSOC)) {
        $output .= '<option value="' . htmlspecialchars($row["product_id"]) . '">' 
                 . htmlspecialchars($row["product_name"]) . '</option>';
    }
    return $output;
}

// ---------------------- Order Processing Logic ----------------------
if (isset($_POST['btnsaveorder'])) {
    $employee_id = $_SESSION['employee_id'] ?? 1;
    $order_date  = date('Y-m-d');
    $order_time  = date('H:i:s');
    
    // Sanitize numeric fields
    $subtotal     = filter_var($_POST['txtsubtotal'], FILTER_SANITIZE_NUMBER_FLOAT, FILTER_FLAG_ALLOW_FRACTION);
    $discount     = filter_var($_POST['txtdiscount'], FILTER_SANITIZE_NUMBER_FLOAT, FILTER_FLAG_ALLOW_FRACTION);
    $total        = filter_var($_POST['txttotal'], FILTER_SANITIZE_NUMBER_FLOAT, FILTER_FLAG_ALLOW_FRACTION);
    $payment_type = htmlspecialchars($_POST['rb']);
    $paid         = filter_var($_POST['txtpaid'], FILTER_SANITIZE_NUMBER_FLOAT, FILTER_FLAG_ALLOW_FRACTION);
    $due          = max($total - $paid, 0);

    // Process hidden CSV fields; here we expect each hidden input (pid_arr, quantity_arr, etc.) to have a CSV string
    $arr_product_id = array_map('intval', explode(',', $_POST['pid_arr'][0] ?? ''));
    $arr_qty        = array_map('intval', explode(',', $_POST['quantity_arr'][0] ?? ''));
    $arr_price      = array_map('floatval', explode(',', $_POST['price_c_arr'][0] ?? ''));
    $arr_total      = array_map('floatval', explode(',', $_POST['saleprice_arr'][0] ?? ''));

    if (empty($arr_product_id) || $arr_product_id[0] === 0) {
        die("No products in order");
    }

    try {
        $pdo->beginTransaction();

        if ($edit_mode) {
            // ----- EDIT ORDER PROCESS -----
            // Restore original stock quantities from existing invoice details
            foreach ($invoice_details as $detail) {
                $update_stock = $pdo->prepare("UPDATE products 
                    SET stock = stock + :qty 
                    WHERE product_id = :product_id");
                $update_stock->execute([
                    ':qty' => $detail['quantity'],
                    ':product_id' => $detail['product_id']
                ]);
            }
            // Delete old invoice details
            $delete_details = $pdo->prepare("DELETE FROM invoice_details WHERE invoice_id = :id");
            $delete_details->execute([':id' => $order_id]);

            // Update main invoice (note: no updated_at in the new schema)
            $update_invoice = $pdo->prepare("UPDATE invoices SET
                employee_id = :employee_id,
                subtotal = :subtotal,
                discount = :discount,
                total = :total,
                payment_type = :payment_type,
                paid = :paid,
                due = :due
                WHERE invoice_id = :id");
            $update_invoice->execute([
                ':employee_id' => $employee_id,
                ':subtotal' => $subtotal,
                ':discount' => $discount,
                ':total' => $total,
                ':payment_type' => $payment_type,
                ':paid' => $paid,
                ':due' => $due,
                ':id' => $order_id
            ]);

            // Insert new invoice details and update stock
            foreach ($arr_product_id as $index => $product_id) {
                $qty = $arr_qty[$index] ?? 0;
                $price = $arr_price[$index] ?? 0;
                $total_price = $arr_total[$index] ?? 0;

                $insert_detail = $pdo->prepare("INSERT INTO invoice_details 
                    (invoice_id, product_id, quantity, unit_price, total_price)
                    VALUES (:invoice_id, :product_id, :qty, :unit_price, :total_price)");
                $insert_detail->execute([
                    ':invoice_id' => $order_id,
                    ':product_id' => $product_id,
                    ':qty' => $qty,
                    ':unit_price' => $price,
                    ':total_price' => $total_price
                ]);

                $update_stock = $pdo->prepare("UPDATE products 
                    SET stock = stock - :qty 
                    WHERE product_id = :product_id");
                $update_stock->execute([
                    ':qty' => $qty,
                    ':product_id' => $product_id
                ]);
            }
        } else {
            // ----- NEW ORDER PROCESS -----
            $invoice_stmt = $pdo->prepare("INSERT INTO invoices 
                (employee_id, order_date, order_time, subtotal, discount, total, paid, due, payment_type)
                VALUES (:employee_id, :order_date, :order_time, :subtotal, :discount, :total, :paid, :due, :payment_type)");
            $invoice_stmt->execute([
                ':employee_id' => $employee_id,
                ':order_date'  => $order_date,
                ':order_time'  => $order_time,
                ':subtotal'    => $subtotal,
                ':discount'    => $discount,
                ':total'       => $total,
                ':paid'        => $paid,
                ':due'         => $due,
                ':payment_type'=> $payment_type
            ]);
            $order_id = $pdo->lastInsertId();

            foreach ($arr_product_id as $index => $product_id) {
                $qty = $arr_qty[$index] ?? 0;
                $price = $arr_price[$index] ?? 0;
                $total_price = $arr_total[$index] ?? 0;

                $insert_detail = $pdo->prepare("INSERT INTO invoice_details 
                    (invoice_id, product_id, quantity, unit_price, total_price)
                    VALUES (:invoice_id, :product_id, :qty, :unit_price, :total_price)");
                $insert_detail->execute([
                    ':invoice_id' => $order_id,
                    ':product_id' => $product_id,
                    ':qty' => $qty,
                    ':unit_price' => $price,
                    ':total_price' => $total_price
                ]);

                $update_stock = $pdo->prepare("UPDATE products 
                    SET stock = stock - :qty 
                    WHERE product_id = :product_id");
                $update_stock->execute([
                    ':qty' => $qty,
                    ':product_id' => $product_id
                ]);
            }
        }

        $pdo->commit();
        header("Location: orderlist.php?success=1");
        exit();
    } catch (Exception $e) {
        if ($pdo->inTransaction()) {
            $pdo->rollBack();
        }
        die("Error processing order: " . $e->getMessage());
    }
}
ob_end_flush();
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>School Store POS - <?= $edit_mode ? "Edit Order" : "New Order" ?></title>
    <!-- Include your CSS files -->
    <link rel="stylesheet" href="assets/css/bootstrap.min.css">
    <link rel="stylesheet" href="assets/css/select2.min.css">
    <style>
        .tableFixHead {
            overflow: auto;
            height: 520px;
        }
        .tableFixHead thead th {
            position: sticky;
            top: 0;
            background: #eee;
            z-index: 1;
        }
    </style>
</head>
<body class="hold-transition sidebar-mini layout-fixed">
<div class="wrapper">
    <!-- Content Wrapper -->
    <div class="content-wrapper">
        <section class="content">
            <div class="container-fluid">
                <div class="row">
                    <div class="col-md-12">
                        <div class="card card-primary">
                            <div class="card-header">
                                <h3 class="card-title"><?= $edit_mode ? "Edit Order" : "New Order" ?></h3>
                            </div>
                            <form method="post" id="posForm">
                                <?php if ($edit_mode): ?>
                                    <input type="hidden" name="order_id" value="<?= $order_id ?>">
                                <?php endif; ?>
                                <div class="card-body">
                                    <div class="row">
                                        <!-- Product Selection Column -->
                                        <div class="col-md-8">
                                            <!-- Barcode Input -->
                                            <div class="input-group mb-3">
                                                <div class="input-group-prepend">
                                                    <span class="input-group-text"><i class="fas fa-barcode"></i></span>
                                                </div>
                                                <input type="text" class="form-control" id="txtbarcode" name="txtbarcode" placeholder="Scan Barcode" autocomplete="off" autofocus>
                                                <div class="input-group-append">
                                                    <button type="button" class="btn btn-secondary" id="clearBarcode">Clear</button>
                                                </div>
                                            </div>
                                            
                                            <!-- Product Dropdown -->
                                            <select class="form-control select2" id="productSelect">
                                                <option value="">Select Product</option>
                                                <?= fill_product($pdo) ?>
                                            </select>
                                            
                                            <!-- Order Items Table -->
                                            <div class="tableFixHead mt-3">
                                                <table class="table table-bordered">
                                                    <thead class="thead-light">
                                                        <tr>
                                                            <th>Product</th>
                                                            <th>Stock</th>
                                                            <th>Price</th>
                                                            <th>Quantity</th>
                                                            <th>Total</th>
                                                            <th>Action</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody id="orderItems">
                                                        <!-- Dynamic content added via JavaScript -->
                                                    </tbody>
                                                </table>
                                            </div>
                                        </div>
                                        
                                        <!-- Payment Section -->
                                        <div class="col-md-4">
                                            <div class="bg-light p-3 rounded">
                                                <!-- Subtotal -->
                                                <div class="form-group">
                                                    <label>Subtotal</label>
                                                    <div class="input-group">
                                                        <div class="input-group-prepend">
                                                            <span class="input-group-text">₱</span>
                                                        </div>
                                                        <input type="text" class="form-control" id="subtotal" name="txtsubtotal" value="<?= $edit_mode ? $invoice['subtotal'] : '' ?>" readonly>
                                                    </div>
                                                </div>
                                                
                                                <!-- Discount -->
                                                <div class="form-group">
                                                    <label>Discount (%)</label>
                                                    <input type="number" class="form-control" id="discount" name="txtdiscount" value="<?= $edit_mode ? $invoice['discount'] : 0 ?>" min="0" max="100">
                                                </div>
                                                
                                                <!-- Total -->
                                                <div class="form-group">
                                                    <label>Total</label>
                                                    <div class="input-group">
                                                        <div class="input-group-prepend">
                                                            <span class="input-group-text">₱</span>
                                                        </div>
                                                        <input type="text" class="form-control" id="total" name="txttotal" value="<?= $edit_mode ? $invoice['total'] : '' ?>" readonly>
                                                    </div>
                                                </div>
                                                
                                                <!-- Payment Type -->
                                                <div class="form-group">
                                                        <label>Payment Type</label>
                                                        <div class="btn-group btn-group-toggle w-100" data-toggle="buttons">
                                                            <label class="btn btn-outline-success active">
                                                                <input type="radio" name="rb" value="Cash" checked> Cash
                                                            </label>
                                                        </div>
                                                    </div>
                                                
                                                <!-- Amount Paid -->
                                                <div class="form-group">
                                                    <label>Amount Paid</label>
                                                    <div class="input-group">
                                                        <div class="input-group-prepend">
                                                            <span class="input-group-text">₱</span>
                                                        </div>
                                                        <input type="number" class="form-control" id="paid" name="txtpaid" value="<?= $edit_mode ? $invoice['paid'] : '' ?>" step="0.01" required>
                                                    </div>
                                                </div>
                                                
                                                <!-- Change Due -->
                                                <div class="form-group">
                                                    <label>Change Due</label>
                                                    <div class="input-group">
                                                        <div class="input-group-prepend">
                                                            <span class="input-group-text">₱</span>
                                                        </div>
                                                        <input type="text" class="form-control" id="due" name="txtdue" value="<?= $edit_mode ? $invoice['due'] : '' ?>" readonly>
                                                    </div>
                                                </div>
                                                
                                                <!-- Submit Button -->
                                                <button type="submit" class="btn btn-success btn-lg btn-block mt-4" name="btnsaveorder" id="saveOrder">
                                                    <?= $edit_mode ? "Update Order" : "Complete Order" ?>
                                                </button>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                
                                <!-- Hidden Fields for Product Data as CSV values -->
                                <input type="hidden" name="pid_arr[]" id="pid_arr">
                                <input type="hidden" name="quantity_arr[]" id="quantity_arr">
                                <input type="hidden" name="price_c_arr[]" id="price_c_arr">
                                <input type="hidden" name="saleprice_arr[]" id="saleprice_arr">
                            </form>
                        </div>
                    </div>
                </div>
            </div>
        </section>
    </div>

    <?php include_once "footer.php"; ?>
</div>

<!-- ================== JAVASCRIPT SECTION ================== -->
<script src="assets/js/jquery.min.js"></script>
<script src="assets/js/select2.full.min.js"></script>
<script src="assets/js/sweetalert2.all.min.js"></script>
<script>
$(document).ready(function() {
    let orderItems = [];
    
    // If in edit mode, preload existing order items into orderItems array
    <?php if($edit_mode && !empty($order_items)): ?>
        orderItems = <?= json_encode($order_items); ?>;
        renderOrderItems();
    <?php endif; ?>

    // Initialize Select2 for product dropdown
    $('#productSelect').select2({
        theme: 'bootstrap4',
        placeholder: "Search product..."
    });

    // Barcode Input Handler
    $('#txtbarcode').on('input', function() {
        let barcode = $(this).val().trim();
        if(barcode.length >= 3) {
            fetchProduct(barcode, 'barcode');
        }
    });

    // Product Select Handler
    $('#productSelect').on('change', function() {
        let productId = $(this).val();
        if(productId) {
            fetchProduct(productId, 'product');
        }
    });

    // Fetch product data via AJAX
    function fetchProduct(value, type) {
        $.ajax({
            url: 'getproduct.php',
            method: 'GET',
            data: { id: value },
            dataType: 'json',
            success: function(response) {
                if(response.error) {
                    showError(response.error);
                    return;
                }
                addOrUpdateProduct(response);
                updateCalculations();
                clearInputs();
            },
            error: function(xhr) {
                showError(xhr.responseJSON?.error || 'Product not found');
            }
        });
    }

    // Add or update a product in the orderItems array
    function addOrUpdateProduct(product) {
        let existingItem = orderItems.find(item => item.product_id === product.product_id);
        if(existingItem) {
            if((existingItem.qty + 1) > product.stock) {
                showError('Exceeds available stock');
                return;
            }
            existingItem.qty++;
            existingItem.total = existingItem.qty * product.sale_price;
        } else {
            if(product.stock < 1) {
                showError('Product out of stock');
                return;
            }
            orderItems.push({
                product_id: product.product_id,
                product_name: product.product_name,
                stock: product.stock,
                sale_price: product.sale_price,
                qty: 1,
                total: product.sale_price
            });
        }
        renderOrderItems();
        updateHiddenFields();
    }

    // Render the order items table
    function renderOrderItems() {
        $('#orderItems').empty();
        orderItems.forEach((item, index) => {
            let row = `
                <tr data-id="${item.product_id}">
                    <td>${item.product_name}</td>
                    <td>${item.stock}</td>
                    <td>₱${item.sale_price.toFixed(2)}</td>
                    <td>
                        <input type="number" class="form-control qty-input" value="${item.qty}" min="1" max="${item.stock}" data-index="${index}">
                    </td>
                    <td>₱${item.total.toFixed(2)}</td>
                    <td>
                        <button class="btn btn-danger btn-sm remove-item" data-index="${index}">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>`;
            $('#orderItems').append(row);
        });
    }

    // Update hidden CSV fields
    function updateHiddenFields() {
        $('#pid_arr').val(orderItems.map(item => item.product_id).join(','));
        $('#quantity_arr').val(orderItems.map(item => item.qty).join(','));
        $('#price_c_arr').val(orderItems.map(item => item.sale_price).join(','));
        $('#saleprice_arr').val(orderItems.map(item => item.total).join(','));
    }

    // Update overall calculations
    function updateCalculations() {
        let subtotal = orderItems.reduce((sum, item) => sum + item.total, 0);
        let discountPercent = parseFloat($('#discount').val()) || 0;
        let discountAmount = subtotal * (discountPercent / 100);
        let total = subtotal - discountAmount;
        let paid = parseFloat($('#paid').val()) || 0;
        let due = total - paid;
        
        $('#subtotal').val(subtotal.toFixed(2));
        $('#total').val(total.toFixed(2));
        $('#due').val(due.toFixed(2));
        updateHiddenFields();
    }

    // When quantity input changes in any row, update that row and recalculate totals
    $('#orderItems').on('input', '.qty-input', function() {
        let index = $(this).data('index');
        let newQty = parseInt($(this).val());
        if(newQty > orderItems[index].stock) {
            showError('Exceeds available stock');
            $(this).val(orderItems[index].qty);
            return;
        }
        orderItems[index].qty = newQty;
        orderItems[index].total = newQty * orderItems[index].sale_price;
        updateCalculations();
        renderOrderItems();
    });

    // Remove item handler
    $('#orderItems').on('click', '.remove-item', function(e) {
        e.preventDefault();
        let index = $(this).data('index');
        orderItems.splice(index, 1);
        renderOrderItems();
        updateCalculations();
    });

    // Update calculations when discount or paid changes
    $('#discount, #paid').on('input', updateCalculations);

    // Error handling
    function showError(message) {
        $('#txtbarcode').addClass('invalid-barcode');
        setTimeout(() => $('#txtbarcode').removeClass('invalid-barcode'), 500);
        Swal.fire({
            icon: 'error',
            title: 'Error!',
            text: message
        });
    }

    // Clear barcode input and reset product dropdown
    function clearInputs() {
        $('#txtbarcode').val('');
        $('#productSelect').val(null).trigger('change');
    }

    $('#clearBarcode').click(clearInputs);
});
</script>
</body>
</html>
